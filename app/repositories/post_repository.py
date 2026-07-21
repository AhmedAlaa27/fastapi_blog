from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Post, User
from app.repositories.base import BaseRepository


class PostRepository(BaseRepository[Post]):
    model = Post

    SORT_FIELDS = {
        "date_posted": Post.date_posted,
        "title": Post.title,
        "likes": Post.likes,
    }

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

    async def search_posts(
        self,
        db: AsyncSession,
        search: str | None = None,
        author: int | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
        sort: str = "-date_posted",
        skip: int = 0,
        limit: int = 10,
    ) -> tuple[list[Post], int]:
        conditions = []
        if search:
            pattern = f"%{search}%"
            conditions.append(
                or_(
                    Post.title.ilike(pattern),
                    Post.content.ilike(pattern),
                    Post.author.has(User.username.ilike(pattern)),
                )
            )
        if author is not None:
            conditions.append(Post.user_id == author)
        if created_after is not None:
            conditions.append(Post.date_posted >= created_after)
        if created_before is not None:
            conditions.append(Post.date_posted <= created_before)

        count_stmt = select(func.count()).select_from(Post)
        stmt = select(Post).options(selectinload(Post.author))
        for condition in conditions:
            count_stmt = count_stmt.where(condition)
            stmt = stmt.where(condition)

        total = (await db.execute(count_stmt)).scalar() or 0

        field_name = sort.lstrip("-")
        column = self.SORT_FIELDS[field_name]
        stmt = stmt.order_by(column.desc() if sort.startswith("-") else column.asc())
        stmt = stmt.offset(skip).limit(limit)

        result = await db.execute(stmt)
        return list(result.scalars().all()), total

    def create(self, db: AsyncSession, post: Post) -> Post:
        db.add(post)
        return post
