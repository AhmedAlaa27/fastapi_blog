from datetime import UTC, datetime, timedelta

from fastapi import BackgroundTasks
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
from sqlalchemy import delete as sql_delete
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    generate_reset_token,
    hash_password,
    hash_reset_token,
    verify_password,
    verify_refresh_token,
)
from app.exceptions.auth import EmailNotVerifiedError, InvalidCredentialsError, InvalidTokenError
from app.exceptions.base import AlreadyExistsError, AppException, BadRequestError, UnauthorizedError
from app.models import EmailVerificationToken, PasswordResetToken, RefreshToken, User
from app.models.role import Role
from app.repositories.user_repository import UserRepository
from app.schemas.auth import Token
from app.schemas.user import UserCreate
from app.services.email_service import send_password_reset_email, send_verification_email

user_repository = UserRepository()


async def _get_role_by_name(db: AsyncSession, name: str) -> Role:
    result = await db.execute(select(Role).where(Role.name == name))
    role = result.scalars().first()
    if not role:
        raise AppException(f"Role '{name}' is not configured", status_code=500)
    return role


async def _generate_unique_username(db: AsyncSession, base: str) -> str:
    candidate = base[:50] or "user"
    suffix = 0
    while await user_repository.get_by_username(db, candidate):
        suffix += 1
        candidate = f"{base[:46]}{suffix}"
    return candidate


async def _issue_token_pair(db: AsyncSession, user: User) -> Token:
    access_token = create_access_token(data={"sub": str(user.id)})
    refresh_token = create_refresh_token(user.id)

    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=hash_reset_token(refresh_token),
            expires_at=datetime.now(UTC)
            + timedelta(days=settings.refresh_token_expire_days),
        )
    )
    await db.commit()

    return Token(
        access_token=access_token, refresh_token=refresh_token, token_type="bearer"
    )


async def _revoke_all_refresh_tokens(db: AsyncSession, user_id: int) -> None:
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked.is_(False))
        .values(revoked=True)
    )
    await db.commit()


async def register(
    db: AsyncSession, data: UserCreate, background_tasks: BackgroundTasks
) -> User:
    existing_user = await user_repository.get_by_username_or_email(
        db, data.username, data.email
    )
    if existing_user:
        if existing_user.username == data.username:
            raise AlreadyExistsError("Username already exists")
        if existing_user.email == data.email:
            raise AlreadyExistsError("Email already exists")

    author_role = await _get_role_by_name(db, "author")

    new_user = User(
        username=data.username,
        email=data.email.lower(),
        password_hash=hash_password(data.password),
        roles=[author_role],
    )
    user_repository.create(db, new_user)
    await db.commit()
    await db.refresh(new_user)

    token = generate_reset_token()
    token_hash = hash_reset_token(token)
    expires_at = datetime.now(UTC) + timedelta(
        hours=settings.email_verification_token_expire_hours
    )
    db.add(
        EmailVerificationToken(
            user_id=new_user.id,
            token_hash=token_hash,
            expires_at=expires_at,
        )
    )
    await db.commit()

    background_tasks.add_task(
        send_verification_email,
        to_email=new_user.email,
        username=new_user.username,
        token=token,
    )

    return new_user


async def login(db: AsyncSession, email: str, password: str) -> Token:
    user = await user_repository.get_by_email(db, email)

    # Don't reveal which one failed, or whether the account is Google-only
    # (security best practice)
    if not user or user.password_hash is None:
        raise InvalidCredentialsError()

    if not verify_password(password, user.password_hash):
        raise InvalidCredentialsError()

    if not user.email_verified:
        raise EmailNotVerifiedError()

    return await _issue_token_pair(db, user)


async def refresh(db: AsyncSession, refresh_token: str) -> Token:
    user_id = verify_refresh_token(refresh_token)
    if user_id is None:
        raise InvalidTokenError("Invalid or expired refresh token")

    token_hash = hash_reset_token(refresh_token)
    result = await db.execute(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash),
    )
    stored_token = result.scalars().first()

    if not stored_token:
        raise InvalidTokenError("Invalid or expired refresh token")

    if stored_token.revoked:
        # Reuse of an already-rotated/revoked refresh token: treat as compromised.
        await _revoke_all_refresh_tokens(db, stored_token.user_id)
        raise InvalidTokenError(
            "Refresh token reuse detected, all sessions revoked. Please log in again."
        )

    if stored_token.expires_at < datetime.now(UTC):
        raise InvalidTokenError("Invalid or expired refresh token")

    user = await user_repository.get_by_id(db, stored_token.user_id)
    if not user:
        raise InvalidTokenError("Invalid or expired refresh token")

    stored_token.revoked = True

    new_access_token = create_access_token(data={"sub": str(user.id)})
    new_refresh_token = create_refresh_token(user.id)
    new_token_row = RefreshToken(
        user_id=user.id,
        token_hash=hash_reset_token(new_refresh_token),
        expires_at=datetime.now(UTC) + timedelta(days=settings.refresh_token_expire_days),
    )
    db.add(new_token_row)
    await db.flush()
    stored_token.replaced_by_id = new_token_row.id
    await db.commit()

    return Token(
        access_token=new_access_token,
        refresh_token=new_refresh_token,
        token_type="bearer",
    )


async def logout(db: AsyncSession, refresh_token: str) -> int | None:
    token_hash = hash_reset_token(refresh_token)
    result = await db.execute(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash),
    )
    stored_token = result.scalars().first()

    if stored_token and not stored_token.revoked:
        stored_token.revoked = True
        await db.commit()
        return stored_token.user_id
    return None


async def verify_email(db: AsyncSession, token: str) -> User:
    token_hash = hash_reset_token(token)
    result = await db.execute(
        select(EmailVerificationToken).where(
            EmailVerificationToken.token_hash == token_hash,
        ),
    )
    verification_token = result.scalars().first()

    if not verification_token:
        raise BadRequestError("Invalid or expired verification token")

    if verification_token.expires_at < datetime.now(UTC):
        await db.delete(verification_token)
        await db.commit()
        raise BadRequestError("Invalid or expired verification token")

    user = await user_repository.get_by_id(db, verification_token.user_id)
    if not user:
        raise BadRequestError("Invalid or expired verification token")

    user.email_verified = True

    await db.execute(
        sql_delete(EmailVerificationToken).where(
            EmailVerificationToken.user_id == user.id,
        ),
    )
    await db.commit()

    return user


async def google_login(db: AsyncSession, id_token_str: str) -> Token:
    try:
        payload = google_id_token.verify_oauth2_token(
            id_token_str, google_requests.Request(), settings.google_client_id
        )
    except ValueError:
        raise UnauthorizedError("Invalid Google token")

    sub = payload["sub"]
    email = payload["email"].lower()

    result = await db.execute(select(User).where(User.oauth_sub == sub))
    user = result.scalars().first()

    if not user:
        user = await user_repository.get_by_email(db, email)
        if user:
            user.oauth_sub = sub
        else:
            author_role = await _get_role_by_name(db, "author")
            username = await _generate_unique_username(db, email.split("@")[0])
            user = User(
                username=username,
                email=email,
                password_hash=None,
                auth_provider="google",
                oauth_sub=sub,
                email_verified=True,
                roles=[author_role],
            )
            db.add(user)
        await db.commit()
        await db.refresh(user)

    return await _issue_token_pair(db, user)


async def forgot_password(
    db: AsyncSession, email: str, background_tasks: BackgroundTasks
) -> None:
    user = await user_repository.get_by_email(db, email)

    if user:
        await db.execute(
            sql_delete(PasswordResetToken).where(
                PasswordResetToken.user_id == user.id,
            ),
        )

        token = generate_reset_token()
        token_hash = hash_reset_token(token)
        expires_at = datetime.now(UTC) + timedelta(
            minutes=settings.reset_token_expire_minutes
        )

        db.add(
            PasswordResetToken(
                user_id=user.id,
                token_hash=token_hash,
                expires_at=expires_at,
            )
        )
        await db.commit()

        background_tasks.add_task(
            send_password_reset_email,
            to_email=user.email,
            username=user.username,
            token=token,
        )


async def reset_password(db: AsyncSession, token: str, new_password: str) -> User:
    token_hash = hash_reset_token(token)

    result = await db.execute(
        select(PasswordResetToken).where(
            PasswordResetToken.token_hash == token_hash,
        ),
    )
    reset_token = result.scalars().first()

    if not reset_token:
        raise BadRequestError("Invalid or expired reset token")

    if reset_token.expires_at < datetime.now(UTC):
        await db.delete(reset_token)
        await db.commit()
        raise BadRequestError("Invalid or expired reset token")

    user = await user_repository.get_by_id(db, reset_token.user_id)

    if not user:
        raise BadRequestError("Invalid or expired reset token")

    user.password_hash = hash_password(new_password)

    await db.execute(
        sql_delete(PasswordResetToken).where(
            PasswordResetToken.user_id == user.id,
        ),
    )

    await db.commit()

    await _revoke_all_refresh_tokens(db, user.id)

    return user


async def change_password(
    db: AsyncSession, current_user: User, current_password: str, new_password: str
) -> None:
    if current_user.password_hash is None or not verify_password(
        current_password, current_user.password_hash
    ):
        raise BadRequestError("Current password is incorrect")

    current_user.password_hash = hash_password(new_password)

    await db.execute(
        sql_delete(PasswordResetToken).where(
            PasswordResetToken.user_id == current_user.id,
        ),
    )

    await db.commit()

    await _revoke_all_refresh_tokens(db, current_user.id)
