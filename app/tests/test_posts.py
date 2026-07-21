from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models import Post, User

pytestmark = pytest.mark.anyio


async def make_user(db_session: AsyncSession, username: str, email: str) -> User:
    user = User(
        username=username,
        email=email,
        password_hash=hash_password("testpassword123"),
        email_verified=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def make_post(
    db_session: AsyncSession,
    user_id: int,
    title: str,
    content: str,
    likes: int = 0,
    days_ago: int = 0,
) -> Post:
    post = Post(
        title=title,
        content=content,
        user_id=user_id,
        likes=likes,
        date_posted=datetime.now(UTC) - timedelta(days=days_ago),
    )
    db_session.add(post)
    await db_session.commit()
    await db_session.refresh(post)
    return post


@pytest.fixture
async def author(db_session: AsyncSession) -> User:
    return await make_user(db_session, "alice", "alice@example.com")


@pytest.fixture
async def other_author(db_session: AsyncSession) -> User:
    return await make_user(db_session, "bob", "bob@example.com")


@pytest.fixture
async def posts(db_session: AsyncSession, author: User, other_author: User) -> list[Post]:
    return [
        await make_post(
            db_session, author.id, "Intro to FastAPI", "Learn about jwt auth", likes=5, days_ago=5
        ),
        await make_post(
            db_session, author.id, "SQLAlchemy Tips", "Query composition tricks", likes=10, days_ago=3
        ),
        await make_post(
            db_session, other_author.id, "Pydantic Guide", "Validation deep dive", likes=1, days_ago=1
        ),
    ]


class TestSearch:
    async def test_search_title(self, client: AsyncClient, posts):
        response = await client.get("/api/posts", params={"search": "FastAPI"})
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["posts"][0]["title"] == "Intro to FastAPI"

    async def test_search_content(self, client: AsyncClient, posts):
        response = await client.get("/api/posts", params={"search": "jwt"})
        assert response.status_code == 200
        assert response.json()["total"] == 1

    async def test_search_author_username(self, client: AsyncClient, posts):
        response = await client.get("/api/posts", params={"search": "bob"})
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["posts"][0]["author"]["username"] == "bob"

    async def test_search_case_insensitive(self, client: AsyncClient, posts):
        response = await client.get("/api/posts", params={"search": "fastapi"})
        assert response.json()["total"] == 1

    async def test_search_no_match(self, client: AsyncClient, posts):
        response = await client.get("/api/posts", params={"search": "nonexistent"})
        data = response.json()
        assert data["total"] == 0
        assert data["posts"] == []


class TestFilter:
    async def test_filter_by_author(self, client: AsyncClient, posts, author: User):
        response = await client.get("/api/posts", params={"author": author.id})
        data = response.json()
        assert data["total"] == 2
        assert all(p["user_id"] == author.id for p in data["posts"])

    async def test_filter_by_nonexistent_author(self, client: AsyncClient, posts):
        response = await client.get("/api/posts", params={"author": 999999})
        assert response.json()["total"] == 0

    async def test_filter_created_after(self, client: AsyncClient, posts):
        cutoff = (datetime.now(UTC) - timedelta(days=2)).isoformat()
        response = await client.get("/api/posts", params={"created_after": cutoff})
        data = response.json()
        assert data["total"] == 1
        assert data["posts"][0]["title"] == "Pydantic Guide"

    async def test_filter_created_before(self, client: AsyncClient, posts):
        cutoff = (datetime.now(UTC) - timedelta(days=2)).isoformat()
        response = await client.get("/api/posts", params={"created_before": cutoff})
        data = response.json()
        assert data["total"] == 2

    async def test_filter_date_range(self, client: AsyncClient, posts):
        after = (datetime.now(UTC) - timedelta(days=4)).isoformat()
        before = (datetime.now(UTC) - timedelta(days=2)).isoformat()
        response = await client.get(
            "/api/posts", params={"created_after": after, "created_before": before}
        )
        data = response.json()
        assert data["total"] == 1
        assert data["posts"][0]["title"] == "SQLAlchemy Tips"

    async def test_combined_author_and_search(self, client: AsyncClient, posts, author: User):
        response = await client.get(
            "/api/posts", params={"author": author.id, "search": "Tips"}
        )
        data = response.json()
        assert data["total"] == 1
        assert data["posts"][0]["title"] == "SQLAlchemy Tips"


class TestSort:
    async def test_default_sort_is_newest_first(self, client: AsyncClient, posts):
        response = await client.get("/api/posts")
        titles = [p["title"] for p in response.json()["posts"]]
        assert titles == ["Pydantic Guide", "SQLAlchemy Tips", "Intro to FastAPI"]

    async def test_sort_date_posted_ascending(self, client: AsyncClient, posts):
        response = await client.get("/api/posts", params={"sort": "date_posted"})
        titles = [p["title"] for p in response.json()["posts"]]
        assert titles == ["Intro to FastAPI", "SQLAlchemy Tips", "Pydantic Guide"]

    async def test_sort_title_ascending(self, client: AsyncClient, posts):
        response = await client.get("/api/posts", params={"sort": "title"})
        titles = [p["title"] for p in response.json()["posts"]]
        assert titles == sorted(titles)

    async def test_sort_title_descending(self, client: AsyncClient, posts):
        response = await client.get("/api/posts", params={"sort": "-title"})
        titles = [p["title"] for p in response.json()["posts"]]
        assert titles == sorted(titles, reverse=True)

    async def test_invalid_sort_field_returns_400(self, client: AsyncClient, posts):
        response = await client.get("/api/posts", params={"sort": "bogus"})
        assert response.status_code == 400
        assert "Invalid sort field" in response.json()["detail"]


class TestPagination:
    async def test_skip_beyond_total_returns_empty(self, client: AsyncClient, posts):
        response = await client.get("/api/posts", params={"skip": 1000, "limit": 10})
        data = response.json()
        assert data["posts"] == []
        assert data["has_more"] is False

    async def test_limit_boundary(self, client: AsyncClient, posts):
        response = await client.get("/api/posts", params={"skip": 0, "limit": 1})
        data = response.json()
        assert len(data["posts"]) == 1
        assert data["has_more"] is True

    async def test_pagination_with_filter(self, client: AsyncClient, posts, author: User):
        response = await client.get(
            "/api/posts", params={"author": author.id, "skip": 0, "limit": 1}
        )
        data = response.json()
        assert data["total"] == 2
        assert len(data["posts"]) == 1
        assert data["has_more"] is True
