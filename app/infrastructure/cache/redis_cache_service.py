import logging
from typing import Any

from app.infrastructure.cache.client import get_redis_client
from app.infrastructure.cache.serializer import deserialize, serialize
from app.services.cache_service import CacheService

logger = logging.getLogger(__name__)


class RedisCacheService(CacheService):
    async def get(self, key: str) -> Any | None:
        try:
            client = await get_redis_client()
            raw = await client.get(key)
        except Exception:
            logger.warning("cache get failed", extra={"cache_key": key, "cache_result": "error"})
            return None
        if raw is None:
            logger.info("cache miss", extra={"cache_key": key, "cache_result": "miss"})
            return None
        logger.info("cache hit", extra={"cache_key": key, "cache_result": "hit"})
        return deserialize(raw)

    async def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        try:
            client = await get_redis_client()
            await client.set(key, serialize(value), ex=ttl)
        except Exception:
            logger.warning("cache set failed", extra={"cache_key": key})

    async def delete(self, key: str) -> None:
        try:
            client = await get_redis_client()
            await client.delete(key)
        except Exception:
            logger.warning("cache delete failed", extra={"cache_key": key})

    async def exists(self, key: str) -> bool:
        try:
            client = await get_redis_client()
            return bool(await client.exists(key))
        except Exception:
            logger.warning("cache exists check failed", extra={"cache_key": key})
            return False

    async def delete_pattern(self, pattern: str) -> None:
        try:
            client = await get_redis_client()
            keys = [k async for k in client.scan_iter(match=pattern)]
            if keys:
                await client.delete(*keys)
        except Exception:
            logger.warning("cache delete_pattern failed", extra={"cache_pattern": pattern})
