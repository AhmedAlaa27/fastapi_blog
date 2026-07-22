from datetime import UTC, datetime, timedelta
from io import BytesIO

import pytest
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.exceptions.base import PermissionDeniedError
from app.exceptions.posts import PostNotFoundError
from app.exceptions.users import UserNotFoundError
from app.infrastructure.cache.keys import post_detail_key, post_list_key
from app.models import RefreshToken, Role, User
from app.schemas.post import PostCreate, PostUpdate
from app.schemas.user import UserUpdate
from app.services import audit_service, auth_service, post_service, user_service
from app.tests.factories import PostFactory, UserFactory

pytestmark = pytest.mark.anyio


async def _persist(db_session: AsyncSession, obj):
    db_session.add(obj)
    await db_session.commit()
    await db_session.refresh(obj)
    return obj


async def _make_user(db_session: AsyncSession, username: str, email: str, **kwargs) -> User:
    user = await _persist(db_session, UserFactory(username=username, email=email, **kwargs))
    # Eager-load roles/permissions to mirror get_current_user's get_by_id_with_roles,
    # since post_service._authorize_post_mutation reads current_user.roles synchronously.
    result = await db_session.execute(
        select(User)
        .options(selectinload(User.roles).selectinload(Role.permissions))
        .where(User.id == user.id)
    )
    return result.scalars().one()


class TestPostServiceCreate:
    async def test_create_post_persists_and_sets_owner(
        self, db_session: AsyncSession, mocked_redis
    ):
        user = await _make_user(db_session, "creator", "creator@example.com")
        post = await post_service.create_post(
            db_session, PostCreate(title="Hello", content="World"), user
        )
        assert post.id is not None
        assert post.user_id == user.id

    async def test_create_post_invalidates_list_cache(
        self, db_session: AsyncSession, mocked_redis
    ):
        user = await _make_user(db_session, "creator2", "creator2@example.com")
        list_key = post_list_key(0, 10, None, None, None, None, "-date_posted")
        await mocked_redis.set(list_key, '{"stale": true}')

        await post_service.create_post(
            db_session, PostCreate(title="Hello", content="World"), user
        )

        assert await mocked_redis.get(list_key) is None


class TestPostServiceCacheAside:
    async def test_list_posts_cache_hit_skips_repository(
        self, db_session: AsyncSession, mocked_redis, monkeypatch
    ):
        cache_key = post_list_key(0, 10, None, None, None, None, "-date_posted")
        await mocked_redis.set(
            cache_key,
            '{"posts": [], "total": 0, "skip": 0, "limit": 10, "has_more": false}',
        )

        called = False

        async def fail_if_called(*args, **kwargs):
            nonlocal called
            called = True
            raise AssertionError("repository should not be called on cache hit")

        monkeypatch.setattr(post_service.post_repository, "search_posts", fail_if_called)

        result = await post_service.list_posts(db_session, 0, 10)
        assert result.total == 0
        assert called is False

    async def test_list_posts_cache_miss_populates_cache(
        self, db_session: AsyncSession, mocked_redis
    ):
        user = await _make_user(db_session, "lister", "lister@example.com")
        await _persist(db_session, PostFactory(user_id=user.id, title="A"))

        cache_key = post_list_key(0, 10, None, None, None, None, "-date_posted")
        assert await mocked_redis.get(cache_key) is None

        result = await post_service.list_posts(db_session, 0, 10)
        assert result.total == 1
        assert await mocked_redis.get(cache_key) is not None

    async def test_get_post_cache_hit_skips_repository(
        self, db_session: AsyncSession, mocked_redis, monkeypatch
    ):
        cache_key = post_detail_key(1)
        await mocked_redis.set(
            cache_key,
            '{"id": 1, "title": "Cached", "content": "c", "user_id": 1, '
            '"date_posted": "2026-01-01T00:00:00+00:00", '
            '"author": {"id": 1, "username": "x", "image_file": null, "image_path": "/static/profile_pics/default.jpg"}}',
        )

        async def fail_if_called(*args, **kwargs):
            raise AssertionError("repository should not be called on cache hit")

        monkeypatch.setattr(post_service.post_repository, "get_by_id", fail_if_called)

        result = await post_service.get_post(db_session, 1)
        assert result.title == "Cached"

    async def test_get_post_cache_miss_raises_not_found(self, db_session: AsyncSession, mocked_redis):
        with pytest.raises(PostNotFoundError):
            await post_service.get_post(db_session, 999999)


class TestPostServiceMutations:
    async def test_update_post_full_invalidates_caches(
        self, db_session: AsyncSession, mocked_redis
    ):
        user = await _make_user(db_session, "editor", "editor@example.com")
        post = await _persist(db_session, PostFactory(user_id=user.id, title="Old"))
        await mocked_redis.set(post_detail_key(post.id), '{"stale": true}')

        updated = await post_service.update_post_full(
            db_session, post.id, PostCreate(title="New", content="New content"), user
        )
        assert updated.title == "New"
        assert await mocked_redis.get(post_detail_key(post.id)) is None

    async def test_update_post_partial_only_changes_set_fields(
        self, db_session: AsyncSession, mocked_redis
    ):
        user = await _make_user(db_session, "editor2", "editor2@example.com")
        post = await _persist(
            db_session, PostFactory(user_id=user.id, title="Old", content="Original")
        )
        updated = await post_service.update_post_partial(
            db_session, post.id, PostUpdate(title="New Title"), user
        )
        assert updated.title == "New Title"
        assert updated.content == "Original"

    async def test_update_post_non_owner_without_permission_denied(
        self, db_session: AsyncSession, mocked_redis
    ):
        owner = await _make_user(db_session, "owner1", "owner1@example.com")
        other = await _make_user(db_session, "other1", "other1@example.com")
        post = await _persist(db_session, PostFactory(user_id=owner.id, title="Mine"))

        with pytest.raises(PermissionDeniedError):
            await post_service.update_post_full(
                db_session, post.id, PostCreate(title="Hijack", content="c"), other
            )

    async def test_delete_post_removes_row_and_invalidates_cache(
        self, db_session: AsyncSession, mocked_redis
    ):
        user = await _make_user(db_session, "deleter", "deleter@example.com")
        post = await _persist(db_session, PostFactory(user_id=user.id, title="Bye"))
        await mocked_redis.set(post_detail_key(post.id), '{"stale": true}')

        await post_service.delete_post(db_session, post.id, user)

        assert await post_service.post_repository.get_by_id(db_session, post.id) is None
        assert await mocked_redis.get(post_detail_key(post.id)) is None

    async def test_delete_post_non_owner_without_permission_denied(
        self, db_session: AsyncSession, mocked_redis
    ):
        owner = await _make_user(db_session, "owner2", "owner2@example.com")
        other = await _make_user(db_session, "other2", "other2@example.com")
        post = await _persist(db_session, PostFactory(user_id=owner.id, title="Mine"))

        with pytest.raises(PermissionDeniedError):
            await post_service.delete_post(db_session, post.id, other)


class TestUserService:
    async def test_get_user_returns_user(self, db_session: AsyncSession):
        user = await _make_user(db_session, "getme", "getme@example.com")
        found = await user_service.get_user(db_session, user.id)
        assert found.id == user.id

    async def test_get_user_raises_not_found(self, db_session: AsyncSession):
        with pytest.raises(UserNotFoundError):
            await user_service.get_user(db_session, 999999)

    async def test_update_user_changes_fields(self, db_session: AsyncSession):
        user = await _make_user(db_session, "updateme", "updateme@example.com")
        updated = await user_service.update_user(
            db_session, user.id, UserUpdate(username="updated_name"), user
        )
        assert updated.username == "updated_name"

    async def test_update_user_denies_non_owner(self, db_session: AsyncSession):
        user = await _make_user(db_session, "victim", "victim@example.com")
        attacker = await _make_user(db_session, "attacker", "attacker@example.com")
        with pytest.raises(PermissionDeniedError):
            await user_service.update_user(
                db_session, user.id, UserUpdate(username="hijacked"), attacker
            )

    async def test_upload_profile_picture_saves_and_updates_user(
        self, db_session: AsyncSession, storage_service, monkeypatch
    ):
        monkeypatch.setattr(user_service, "local_storage", storage_service)
        user = await _make_user(db_session, "picuser", "picuser@example.com")

        buf = BytesIO()
        Image.new("RGB", (10, 10), color="red").save(buf, format="JPEG")
        content = buf.getvalue()

        class FakeUploadFile:
            async def read(self) -> bytes:
                return content

        updated = await user_service.upload_profile_picture(
            db_session, user.id, user, FakeUploadFile()
        )
        assert updated.image_file is not None

    async def test_delete_profile_picture_clears_field(
        self, db_session: AsyncSession, storage_service, monkeypatch
    ):
        monkeypatch.setattr(user_service, "local_storage", storage_service)
        user = await _make_user(
            db_session, "picuser2", "picuser2@example.com", image_file="something.jpg"
        )
        updated = await user_service.delete_profile_picture(db_session, user.id, user)
        assert updated.image_file is None


class TestAuthServiceRefreshTokens:
    async def test_issue_token_pair_creates_refresh_token_row(self, db_session: AsyncSession):
        user = await _make_user(db_session, "tokenowner", "tokenowner@example.com")
        token = await auth_service._issue_token_pair(db_session, user)

        result = await db_session.execute(
            select(RefreshToken).where(RefreshToken.user_id == user.id)
        )
        rows = result.scalars().all()
        assert len(rows) == 1
        assert rows[0].revoked is False
        assert token.refresh_token

    async def test_refresh_rotates_token_and_links_chain(self, db_session: AsyncSession):
        user = await _make_user(db_session, "rotator", "rotator@example.com")
        first = await auth_service._issue_token_pair(db_session, user)

        second = await auth_service.refresh(db_session, first.refresh_token)

        result = await db_session.execute(
            select(RefreshToken).where(RefreshToken.user_id == user.id)
        )
        rows = {r.token_hash: r for r in result.scalars().all()}
        old_hash = auth_service.hash_reset_token(first.refresh_token)
        new_hash = auth_service.hash_reset_token(second.refresh_token)
        assert rows[old_hash].revoked is True
        assert rows[old_hash].replaced_by_id == rows[new_hash].id
        assert rows[new_hash].revoked is False

    async def test_refresh_expired_token_raises(self, db_session: AsyncSession):
        from app.core.security import create_refresh_token
        from app.exceptions.auth import InvalidTokenError

        user = await _make_user(db_session, "expiredowner", "expiredowner@example.com")
        raw_token = create_refresh_token(user.id)
        await _persist(
            db_session,
            RefreshToken(
                user_id=user.id,
                token_hash=auth_service.hash_reset_token(raw_token),
                expires_at=datetime.now(UTC) - timedelta(days=1),
            ),
        )
        with pytest.raises(InvalidTokenError):
            await auth_service.refresh(db_session, raw_token)

    async def test_refresh_revoked_token_detects_reuse_and_revokes_all(
        self, db_session: AsyncSession
    ):
        from app.exceptions.auth import InvalidTokenError

        user = await _make_user(db_session, "reuser", "reuser@example.com")
        first = await auth_service._issue_token_pair(db_session, user)
        await auth_service.refresh(db_session, first.refresh_token)

        with pytest.raises(InvalidTokenError):
            await auth_service.refresh(db_session, first.refresh_token)

        result = await db_session.execute(
            select(RefreshToken).where(RefreshToken.user_id == user.id)
        )
        assert all(r.revoked for r in result.scalars().all())

    async def test_revoke_all_refresh_tokens(self, db_session: AsyncSession):
        user = await _make_user(db_session, "revokeall", "revokeall@example.com")
        await auth_service._issue_token_pair(db_session, user)
        await auth_service._issue_token_pair(db_session, user)

        await auth_service._revoke_all_refresh_tokens(db_session, user.id)

        result = await db_session.execute(
            select(RefreshToken).where(RefreshToken.user_id == user.id)
        )
        assert all(r.revoked for r in result.scalars().all())


class TestAuditService:
    async def test_log_event_creates_audit_log(self, db_session: AsyncSession):
        from unittest.mock import MagicMock

        user = await _make_user(db_session, "auditsvc", "auditsvc@example.com")
        request = MagicMock()
        request.client.host = "1.2.3.4"
        request.headers.get.return_value = "pytest-agent"

        await audit_service.log_event(
            db_session,
            user_id=user.id,
            action="create",
            resource="post",
            resource_id=42,
            request=request,
        )

        from app.models.audit_log import AuditLog

        result = await db_session.execute(
            select(AuditLog).where(AuditLog.user_id == user.id)
        )
        log = result.scalars().one()
        assert log.action == "create"
        assert log.resource == "post"
        assert log.resource_id == 42
        assert log.ip_address == "1.2.3.4"
        assert log.user_agent == "pytest-agent"
