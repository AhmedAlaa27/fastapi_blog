from app.infrastructure.cache.redis_cache_service import RedisCacheService
from app.services.cache_service import CacheService

cache_service: CacheService = RedisCacheService()


async def get_cache() -> CacheService:
    return cache_service
