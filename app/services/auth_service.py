from datetime import UTC, datetime, timedelta

from fastapi import BackgroundTasks, HTTPException, status
from sqlalchemy import delete as sql_delete
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import (
    create_access_token,
    generate_reset_token,
    hash_password,
    hash_reset_token,
    verify_password,
)
from app.models import PasswordResetToken, User
from app.repositories.user_repository import UserRepository
from app.schemas.auth import Token
from app.schemas.user import UserCreate
from app.services.email_service import send_password_reset_email

user_repository = UserRepository()


async def register(db: AsyncSession, data: UserCreate) -> User:
    existing_user = await user_repository.get_by_username_or_email(
        db, data.username, data.email
    )
    if existing_user:
        if existing_user.username == data.username:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Username already exists",
            )
        if existing_user.email == data.email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already exists",
            )

    new_user = User(
        username=data.username,
        email=data.email.lower(),
        password_hash=hash_password(data.password),
    )
    user_repository.create(db, new_user)
    await db.commit()
    await db.refresh(new_user)

    return new_user


async def login(db: AsyncSession, email: str, password: str) -> Token:
    user = await user_repository.get_by_email(db, email)

    # Don't reveal which one failed (security best practice)
    if not user or not verify_password(password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token_expires = timedelta(minutes=settings.access_token_expire_minutes)
    access_token = create_access_token(
        data={"sub": str(user.id)},
        expires_delta=access_token_expires,
    )
    return Token(access_token=access_token, token_type="bearer")


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


async def reset_password(db: AsyncSession, token: str, new_password: str) -> None:
    token_hash = hash_reset_token(token)

    result = await db.execute(
        select(PasswordResetToken).where(
            PasswordResetToken.token_hash == token_hash,
        ),
    )
    reset_token = result.scalars().first()

    if not reset_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token",
        )

    if reset_token.expires_at < datetime.now(UTC):
        await db.delete(reset_token)
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token",
        )

    user = await user_repository.get_by_id(db, reset_token.user_id)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token",
        )

    user.password_hash = hash_password(new_password)

    await db.execute(
        sql_delete(PasswordResetToken).where(
            PasswordResetToken.user_id == user.id,
        ),
    )

    await db.commit()


async def change_password(
    db: AsyncSession, current_user: User, current_password: str, new_password: str
) -> None:
    if not verify_password(current_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )

    current_user.password_hash = hash_password(new_password)

    await db.execute(
        sql_delete(PasswordResetToken).where(
            PasswordResetToken.user_id == current_user.id,
        ),
    )

    await db.commit()
