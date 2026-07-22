import pytest

from app.infrastructure.cache.redis_cache_service import RedisCacheService

pytestmark = pytest.mark.anyio


class TestRedisCacheServiceDirect:
    async def test_set_then_get_roundtrip(self, cache_service: RedisCacheService):
        await cache_service.set("k1", {"hello": "world"})
        assert await cache_service.get("k1") == {"hello": "world"}

    async def test_get_missing_key_returns_none(self, cache_service: RedisCacheService):
        assert await cache_service.get("does-not-exist") is None

    async def test_delete_removes_key(self, cache_service: RedisCacheService):
        await cache_service.set("k2", "value")
        await cache_service.delete("k2")
        assert await cache_service.get("k2") is None

    async def test_exists_true_after_set(self, cache_service: RedisCacheService):
        await cache_service.set("k3", "value")
        assert await cache_service.exists("k3") is True

    async def test_exists_false_when_missing(self, cache_service: RedisCacheService):
        assert await cache_service.exists("nope") is False

    async def test_delete_pattern_clears_matching_keys(
        self, cache_service: RedisCacheService, redis_client
    ):
        await cache_service.set("posts:list:a", "1")
        await cache_service.set("posts:list:b", "2")
        await cache_service.set("posts:5", "keep-me")

        await cache_service.delete_pattern("posts:list:*")

        assert await cache_service.get("posts:list:a") is None
        assert await cache_service.get("posts:list:b") is None
        assert await cache_service.get("posts:5") == "keep-me"

    async def test_set_respects_ttl(self, cache_service: RedisCacheService, redis_client):
        await cache_service.set("k4", "value", ttl=60)
        ttl = await redis_client.ttl("k4")
        assert 0 < ttl <= 60
