from typing import Generic, TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

ModelType = TypeVar("ModelType")


class BaseRepository(Generic[ModelType]):
    model: type[ModelType]

    async def get_by_id(self, db: AsyncSession, id_: int) -> ModelType | None:
        result = await db.execute(select(self.model).where(self.model.id == id_))
        return result.scalars().first()

    async def delete(self, db: AsyncSession, obj: ModelType) -> None:
        await db.delete(obj)
