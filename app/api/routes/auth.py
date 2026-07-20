from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import CurrentUser
from app.core.rate_limit import limiter
from app.db.session import get_db
from app.schemas.auth import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    GoogleAuthRequest,
    LogoutRequest,
    RefreshRequest,
    ResetPasswordRequest,
    Token,
    VerifyEmailRequest,
)
from app.schemas.user import UserCreate, UserPrivate
from app.services import auth_service

router = APIRouter()


@router.post(
    "",
    response_model=UserPrivate,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit("5/hour")
async def create_user(
    request: Request,
    user: UserCreate,
    background_tasks: BackgroundTasks,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return await auth_service.register(db, user, background_tasks)


@router.post("/token", response_model=Token)
@limiter.limit("5/minute")
async def login_for_access_token(
    request: Request,
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    # Note: OAuth2PasswordRequestForm uses "username" field, but we treat it as email
    return await auth_service.login(db, form_data.username, form_data.password)


@router.post("/refresh", response_model=Token)
@limiter.limit("10/minute")
async def refresh_token(
    request: Request,
    request_data: RefreshRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return await auth_service.refresh(db, request_data.refresh_token)


@router.post("/logout", status_code=status.HTTP_200_OK)
async def logout(
    request_data: LogoutRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    await auth_service.logout(db, request_data.refresh_token)
    return {"message": "Logged out successfully"}


@router.post("/oauth/google", response_model=Token)
async def google_login(
    request_data: GoogleAuthRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return await auth_service.google_login(db, request_data.id_token)


@router.get("/me", response_model=UserPrivate)
async def get_current_user_info(current_user: CurrentUser):
    """Get the currently authenticated user."""
    return current_user


@router.post("/verify-email", status_code=status.HTTP_200_OK)
async def verify_email(
    request_data: VerifyEmailRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    await auth_service.verify_email(db, request_data.token)
    return {"message": "Email verified successfully. You can now log in."}


@router.post("/forgot-password", status_code=status.HTTP_202_ACCEPTED)
@limiter.limit("3/hour")
async def forgot_password(
    request: Request,
    request_data: ForgotPasswordRequest,
    background_tasks: BackgroundTasks,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    await auth_service.forgot_password(db, request_data.email, background_tasks)
    return {
        "message": "If an account exists with this email, you will receive password reset instructions."
    }


@router.post("/reset-password", status_code=status.HTTP_200_OK)
async def reset_password(
    request_data: ResetPasswordRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    await auth_service.reset_password(db, request_data.token, request_data.new_password)
    return {
        "message": "Password reset successfully. You can now log in with your new password."
    }


@router.patch("/me/password", status_code=status.HTTP_200_OK)
async def change_password(
    password_data: ChangePasswordRequest,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    await auth_service.change_password(
        db,
        current_user,
        password_data.current_password,
        password_data.new_password,
    )
    return {"message": "Password changed successfully"}
