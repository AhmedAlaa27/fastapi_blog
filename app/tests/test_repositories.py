from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Post, User
from app.models.audit_log import AuditLog
from app.repositories.audit_repository import AuditRepository
from app.repositories.post_repository import PostRepository
from app.repositories.user_repository import UserRepository
from app.tests.factories import PostFactory, UserFactory

pytestmark = pytest.mark.anyio

user_repository = UserRepository()
post_repository = PostRepository()
audit_repository = AuditRepository()


async def _persist(db_session: AsyncSession, obj):
    db_session.add(obj)
    await db_session.commit()
    await db_session.refresh(obj)
    return obj


class TestUserRepository:
    async def test_create_adds_user_to_session(self, db_session: AsyncSession):
        user = UserFactory(username="alice", email="alice@example.com")
        user_repository.create(db_session, user)
        await db_session.commit()
        await db_session.refresh(user)
        assert user.id is not None

    async def test_get_by_id_returns_user(self, db_session: AsyncSession):
        user = await _persist(db_session, UserFactory(username="bob", email="bob@example.com"))
        found = await user_repository.get_by_id(db_session, user.id)
        assert found is not None
        assert found.email == "bob@example.com"

    async def test_get_by_id_returns_none_when_missing(self, db_session: AsyncSession):
        assert await user_repository.get_by_id(db_session, 999999) is None

    async def test_get_by_id_with_roles_eager_loads_permissions(
        self, db_session: AsyncSession
    ):
        from sqlalchemy import select

        from app.models.role import Role

        role = (
            await db_session.execute(select(Role).where(Role.name == "author"))
        ).scalars().one()
        user = await _persist(
            db_session,
            UserFactory(username="carol", email="carol@example.com", roles=[role]),
        )

        found = await user_repository.get_by_id_with_roles(db_session, user.id)
        assert found is not None
        assert {r.name for r in found.roles} == {"author"}
        assert {p.name for r in found.roles for p in r.permissions} == {"posts:create"}

    async def test_get_by_email_matches(self, db_session: AsyncSession):
        await _persist(db_session, UserFactory(username="dave", email="dave@example.com"))
        found = await user_repository.get_by_email(db_session, "dave@example.com")
        assert found is not None
        assert found.username == "dave"

    async def test_get_by_email_case_insensitive(self, db_session: AsyncSession):
        await _persist(db_session, UserFactory(username="erin", email="erin@example.com"))
        found = await user_repository.get_by_email(db_session, "ERIN@EXAMPLE.COM")
        assert found is not None
        assert found.username == "erin"

    async def test_get_by_username_matches(self, db_session: AsyncSession):
        await _persist(db_session, UserFactory(username="frank", email="frank@example.com"))
        found = await user_repository.get_by_username(db_session, "frank")
        assert found is not None

    async def test_get_by_username_case_insensitive(self, db_session: AsyncSession):
        await _persist(db_session, UserFactory(username="grace", email="grace@example.com"))
        found = await user_repository.get_by_username(db_session, "GRACE")
        assert found is not None

    async def test_get_by_username_or_email_detects_duplicate_username(
        self, db_session: AsyncSession
    ):
        await _persist(db_session, UserFactory(username="heidi", email="heidi@example.com"))
        found = await user_repository.get_by_username_or_email(
            db_session, "heidi", "someone-else@example.com"
        )
        assert found is not None
        assert found.username == "heidi"

    async def test_get_by_username_or_email_detects_duplicate_email(
        self, db_session: AsyncSession
    ):
        await _persist(db_session, UserFactory(username="ivan", email="ivan@example.com"))
        found = await user_repository.get_by_username_or_email(
            db_session, "someone-else", "ivan@example.com"
        )
        assert found is not None
        assert found.email == "ivan@example.com"

    async def test_get_by_username_or_email_no_match_returns_none(
        self, db_session: AsyncSession
    ):
        found = await user_repository.get_by_username_or_email(
            db_session, "nobody", "nobody@example.com"
        )
        assert found is None


class TestPostRepository:
    async def _make_user(self, db_session: AsyncSession, username: str, email: str) -> User:
        return await _persist(db_session, UserFactory(username=username, email=email))

    async def _make_post(
        self,
        db_session: AsyncSession,
        user_id: int,
        title: str = "Title",
        content: str = "Content",
        likes: int = 0,
        days_ago: int = 0,
    ) -> Post:
        post = PostFactory(
            user_id=user_id,
            title=title,
            content=content,
            likes=likes,
            date_posted=datetime.now(UTC) - timedelta(days=days_ago),
        )
        return await _persist(db_session, post)

    async def test_create_adds_post_to_session(self, db_session: AsyncSession):
        user = await self._make_user(db_session, "author1", "author1@example.com")
        post = PostFactory(user_id=user.id, title="Hello")
        post_repository.create(db_session, post)
        await db_session.commit()
        await db_session.refresh(post)
        assert post.id is not None

    async def test_get_by_id_eager_loads_author(self, db_session: AsyncSession):
        user = await self._make_user(db_session, "author2", "author2@example.com")
        post = await self._make_post(db_session, user.id, title="Post A")
        found = await post_repository.get_by_id(db_session, post.id)
        assert found is not None
        assert found.author.username == "author2"

    async def test_get_by_id_returns_none_when_missing(self, db_session: AsyncSession):
        assert await post_repository.get_by_id(db_session, 999999) is None

    async def test_count_all(self, db_session: AsyncSession):
        user = await self._make_user(db_session, "author3", "author3@example.com")
        await self._make_post(db_session, user.id, title="P1")
        await self._make_post(db_session, user.id, title="P2")
        assert await post_repository.count_all(db_session) == 2

    async def test_count_by_user(self, db_session: AsyncSession):
        u1 = await self._make_user(db_session, "author4", "author4@example.com")
        u2 = await self._make_user(db_session, "author5", "author5@example.com")
        await self._make_post(db_session, u1.id, title="P1")
        await self._make_post(db_session, u1.id, title="P2")
        await self._make_post(db_session, u2.id, title="P3")
        assert await post_repository.count_by_user(db_session, u1.id) == 2
        assert await post_repository.count_by_user(db_session, u2.id) == 1

    async def test_list_paginated_orders_newest_first(self, db_session: AsyncSession):
        user = await self._make_user(db_session, "author6", "author6@example.com")
        await self._make_post(db_session, user.id, title="Old", days_ago=5)
        await self._make_post(db_session, user.id, title="New", days_ago=0)
        posts = await post_repository.list_paginated(db_session, skip=0, limit=10)
        assert [p.title for p in posts] == ["New", "Old"]

    async def test_list_paginated_respects_skip_and_limit(self, db_session: AsyncSession):
        user = await self._make_user(db_session, "author7", "author7@example.com")
        for i in range(3):
            await self._make_post(db_session, user.id, title=f"P{i}", days_ago=i)
        posts = await post_repository.list_paginated(db_session, skip=1, limit=1)
        assert len(posts) == 1

    async def test_list_by_user_paginated(self, db_session: AsyncSession):
        u1 = await self._make_user(db_session, "author8", "author8@example.com")
        u2 = await self._make_user(db_session, "author9", "author9@example.com")
        await self._make_post(db_session, u1.id, title="Mine")
        await self._make_post(db_session, u2.id, title="Theirs")
        posts = await post_repository.list_by_user_paginated(db_session, u1.id, 0, 10)
        assert [p.title for p in posts] == ["Mine"]

    async def test_search_posts_by_title(self, db_session: AsyncSession):
        user = await self._make_user(db_session, "author10", "author10@example.com")
        await self._make_post(db_session, user.id, title="FastAPI Guide")
        await self._make_post(db_session, user.id, title="Other")
        posts, total = await post_repository.search_posts(db_session, search="FastAPI")
        assert total == 1
        assert posts[0].title == "FastAPI Guide"

    async def test_search_posts_by_author(self, db_session: AsyncSession):
        u1 = await self._make_user(db_session, "author11", "author11@example.com")
        u2 = await self._make_user(db_session, "author12", "author12@example.com")
        await self._make_post(db_session, u1.id, title="Mine")
        await self._make_post(db_session, u2.id, title="Theirs")
        posts, total = await post_repository.search_posts(db_session, author=u1.id)
        assert total == 1
        assert posts[0].title == "Mine"

    async def test_search_posts_date_range(self, db_session: AsyncSession):
        user = await self._make_user(db_session, "author13", "author13@example.com")
        await self._make_post(db_session, user.id, title="Recent", days_ago=1)
        await self._make_post(db_session, user.id, title="Ancient", days_ago=10)
        after = datetime.now(UTC) - timedelta(days=5)
        posts, total = await post_repository.search_posts(db_session, created_after=after)
        assert total == 1
        assert posts[0].title == "Recent"

    async def test_search_posts_sort_by_likes_ascending(self, db_session: AsyncSession):
        user = await self._make_user(db_session, "author14", "author14@example.com")
        await self._make_post(db_session, user.id, title="Low", likes=1)
        await self._make_post(db_session, user.id, title="High", likes=10)
        posts, _ = await post_repository.search_posts(db_session, sort="likes")
        assert [p.title for p in posts] == ["Low", "High"]

    async def test_search_posts_pagination(self, db_session: AsyncSession):
        user = await self._make_user(db_session, "author15", "author15@example.com")
        for i in range(3):
            await self._make_post(db_session, user.id, title=f"P{i}", days_ago=i)
        posts, total = await post_repository.search_posts(db_session, skip=1, limit=1)
        assert total == 3
        assert len(posts) == 1


class TestAuditRepository:
    async def test_create_adds_audit_log(self, db_session: AsyncSession):
        user = await _persist(
            db_session, UserFactory(username="auditee", email="auditee@example.com")
        )
        log = AuditLog(
            user_id=user.id,
            action="create",
            resource="post",
            resource_id=1,
            ip_address="127.0.0.1",
            user_agent="pytest",
        )
        audit_repository.create(db_session, log)
        await db_session.commit()
        await db_session.refresh(log)
        assert log.id is not None
        assert log.action == "create"
