import logging
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.dependencies.cache import get_cache
from app.services.cache_service import CacheService

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/health")
async def health() -> dict:
    return {"status": "healthy"}


@router.get("/ready")
async def ready(
    db: Annotated[AsyncSession, Depends(get_db)],
    cache: Annotated[CacheService, Depends(get_cache)],
):
    try:
        await db.execute(text("SELECT 1"))
    except Exception:
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "detail": "database unavailable"},
        )

    if not await cache.exists("__health_check__"):
        logger.warning("redis unavailable during readiness check")

    return {"status": "ready"}


@router.get("/live")
async def live() -> dict:
    return {"status": "alive"}
