from PIL import UnidentifiedImageError
from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.exceptions.base import AlreadyExistsError, BadRequestError, NotFoundError, PermissionDeniedError
from app.exceptions.users import UserNotFoundError
from app.models import User
from app.repositories.user_repository import UserRepository
from app.schemas.user import UserUpdate
from app.storage.local_storage import local_storage

user_repository = UserRepository()


async def get_user(db: AsyncSession, user_id: int) -> User:
    user = await user_repository.get_by_id(db, user_id)
    if not user:
        raise UserNotFoundError()
    return user


async def update_user(
    db: AsyncSession, user_id: int, data: UserUpdate, current_user: User
) -> User:
    if user_id != current_user.id:
        raise PermissionDeniedError("Not authorized to update this user")
    user = await get_user(db, user_id)

    if data.username and data.username.lower() != user.username.lower():
        if await user_repository.get_by_username(db, data.username):
            raise AlreadyExistsError("Username already exists")

    if data.email and data.email.lower() != user.email.lower():
        if await user_repository.get_by_email(db, data.email):
            raise AlreadyExistsError("Email already exists")

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if field == "email":
            value = value.lower()
        setattr(user, field, value)

    await db.commit()
    await db.refresh(user)
    return user


async def delete_user(db: AsyncSession, user_id: int, current_user: User) -> None:
    if user_id != current_user.id:
        raise PermissionDeniedError("Not authorized to delete this user")
    user = await get_user(db, user_id)

    old_image = user.image_file
    if old_image:
        local_storage.delete_profile_image(old_image)

    await user_repository.delete(db, user)
    await db.commit()


async def upload_profile_picture(
    db: AsyncSession, user_id: int, current_user: User, file: UploadFile
) -> User:
    if current_user.id != user_id:
        raise PermissionDeniedError("Not authorized to update this user's picture")

    content = await file.read()

    if len(content) > settings.max_upload_size_bytes:
        raise BadRequestError(
            f"File too large. Maximum size is {settings.max_upload_size_bytes // (1024 * 1024)}MB"
        )

    try:
        new_filename = await local_storage.save_profile_image(content)
    except UnidentifiedImageError as err:
        raise BadRequestError(
            "Invalid image file. Please upload a valid image (JPEG, PNG, GIF, WebP)."
        ) from err

    old_filename = current_user.image_file

    current_user.image_file = new_filename
    await db.commit()
    await db.refresh(current_user)

    if old_filename:
        local_storage.delete_profile_image(old_filename)

    return current_user


async def delete_profile_picture(
    db: AsyncSession, user_id: int, current_user: User
) -> User:
    if current_user.id != user_id:
        raise PermissionDeniedError("Not authorized to update this user's picture")

    old_filename = current_user.image_file

    if not old_filename:
        raise NotFoundError("No profile picture to delete")

    current_user.image_file = None
    await db.commit()
    await db.refresh(current_user)

    local_storage.delete_profile_image(old_filename)

    return current_user
