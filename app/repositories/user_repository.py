from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from app.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    model = User

    async def get_by_email(self, db: AsyncSession, email: str) -> User | None:
        result = await db.execute(
            select(User).where(func.lower(User.email) == email.lower()),
        )
        return result.scalars().first()

    async def get_by_username(self, db: AsyncSession, username: str) -> User | None:
        result = await db.execute(
            select(User).where(func.lower(User.username) == username.lower()),
        )
        return result.scalars().first()

    async def get_by_username_or_email(
        self, db: AsyncSession, username: str, email: str
    ) -> User | None:
        result = await db.execute(
            select(User).where(
                (func.lower(User.username) == username.lower())
                | (func.lower(User.email) == email.lower()),
            ),
        )
        return result.scalars().first()

    def create(self, db: AsyncSession, user: User) -> User:
        db.add(user)
        return user
