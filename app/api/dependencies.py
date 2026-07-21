from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import oauth2_scheme, verify_access_token
from app.db.session import get_db
from app.exceptions.auth import InvalidTokenError
from app.exceptions.base import PermissionDeniedError
from app.models import User
from app.repositories.user_repository import UserRepository

user_repository = UserRepository()


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    user_id = verify_access_token(token)
    if user_id is None:
        raise InvalidTokenError()

    try:
        user_id_int = int(user_id)
    except (TypeError, ValueError):
        raise InvalidTokenError()

    user = await user_repository.get_by_id_with_roles(db, user_id_int)
    if not user:
        raise InvalidTokenError("User not found")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_permission(permission: str):
    async def checker(current_user: CurrentUser) -> User:
        user_permissions = {
            p.name for role in current_user.roles for p in role.permissions
        }
        if permission not in user_permissions:
            raise PermissionDeniedError()
        return current_user

    return checker
