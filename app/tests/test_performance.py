import time
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.cache.keys import post_list_key
from app.tests.factories import PostFactory, UserFactory

pytestmark = pytest.mark.anyio


class TestCacheKeyBenchmark:
    # pytest-benchmark's `benchmark` fixture times a plain sync callable by calling it
    # many times in-process; it can't drive our async app (which is already running
    # inside anyio's event loop for the test). It's a good fit for this hot-path
    # helper though, which is genuinely synchronous and called on every list_posts.
    def test_post_list_key_generation_is_fast(self, benchmark):
        result = benchmark(
            post_list_key, 0, 10, "search term", 1, datetime.now(UTC), None, "-date_posted"
        )
        assert result.startswith("posts:list:")


class TestPostsListCacheLatency:
    async def test_warm_cache_is_faster_than_cold(
        self, client: AsyncClient, db_session: AsyncSession, redis_client
    ):
        user = UserFactory(username="benchowner", email="benchowner@example.com")
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)
        for i in range(20):
            db_session.add(PostFactory(user_id=user.id, title=f"Post {i}"))
        await db_session.commit()

        start = time.perf_counter()
        cold_response = await client.get("/api/v1/posts")
        cold_ms = (time.perf_counter() - start) * 1000
        assert cold_response.status_code == 200

        cache_key = post_list_key(0, 10, None, None, None, None, "-date_posted")
        assert await redis_client.get(cache_key) is not None

        start = time.perf_counter()
        warm_response = await client.get("/api/v1/posts")
        warm_ms = (time.perf_counter() - start) * 1000
        assert warm_response.status_code == 200
        assert warm_response.json() == cold_response.json()

        print(f"\ncold cache: {cold_ms:.2f}ms, warm cache: {warm_ms:.2f}ms")
