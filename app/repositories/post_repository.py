from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Post
from app.repositories.base import BaseRepository


class PostRepository(BaseRepository[Post]):
    model = Post

    async def get_by_id(self, db: AsyncSession, id_: int) -> Post | None:
        result = await db.execute(
            select(Post).options(selectinload(Post.author)).where(Post.id == id_)
        )
        return result.scalars().first()

    async def count_all(self, db: AsyncSession) -> int:
        result = await db.execute(select(func.count()).select_from(Post))
        return result.scalar() or 0

    async def count_by_user(self, db: AsyncSession, user_id: int) -> int:
        result = await db.execute(
            select(func.count()).select_from(Post).where(Post.user_id == user_id)
        )
        return result.scalar() or 0

    async def list_paginated(
        self, db: AsyncSession, skip: int, limit: int
    ) -> list[Post]:
        result = await db.execute(
            select(Post)
            .options(selectinload(Post.author))
            .order_by(Post.date_posted.desc())
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def list_by_user_paginated(
        self, db: AsyncSession, user_id: int, skip: int, limit: int
    ) -> list[Post]:
        result = await db.execute(
            select(Post)
            .options(selectinload(Post.author))
            .where(Post.user_id == user_id)
            .order_by(Post.date_posted.desc())
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())

    def create(self, db: AsyncSession, post: Post) -> Post:
        db.add(post)
        return post
