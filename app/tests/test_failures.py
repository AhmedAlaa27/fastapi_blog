import aiosmtplib
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.infrastructure.cache.redis_cache_service import RedisCacheService
from app.main import app
from app.services import post_service, user_service
from app.tests.conftest import create_test_user

pytestmark = pytest.mark.anyio


class TestRedisFallback:
    async def test_get_post_falls_back_to_db_when_redis_unreachable(
        self, db_session: AsyncSession, mocked_redis, monkeypatch
    ):
        from app.tests.factories import PostFactory, UserFactory

        user = UserFactory(username="fallbackowner", email="fallbackowner@example.com")
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)
        post = PostFactory(user_id=user.id, title="Still readable")
        db_session.add(post)
        await db_session.commit()
        await db_session.refresh(post)

        async def broken_get_client():
            raise ConnectionError("redis unreachable")

        monkeypatch.setattr(
            "app.infrastructure.cache.redis_cache_service.get_redis_client", broken_get_client
        )

        result = await post_service.get_post(db_session, post.id)
        assert result.title == "Still readable"

    async def test_cache_set_failure_does_not_break_create_post(
        self, db_session: AsyncSession, mocked_redis, monkeypatch
    ):
        from app.tests.factories import UserFactory
        from app.schemas.post import PostCreate

        user = UserFactory(username="settermissing", email="settermissing@example.com")
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)

        async def broken_get_client():
            raise ConnectionError("redis unreachable")

        monkeypatch.setattr(
            "app.infrastructure.cache.redis_cache_service.get_redis_client", broken_get_client
        )

        post = await post_service.create_post(
            db_session, PostCreate(title="Survives", content="content"), user
        )
        assert post.id is not None

    async def test_cache_get_logs_warning_on_error(
        self, db_session: AsyncSession, mocked_redis, monkeypatch, caplog
    ):
        async def broken_get_client():
            raise ConnectionError("redis unreachable")

        monkeypatch.setattr(
            "app.infrastructure.cache.redis_cache_service.get_redis_client", broken_get_client
        )

        service = RedisCacheService()
        with caplog.at_level("WARNING"):
            result = await service.get("some-key")

        assert result is None
        assert any("cache get failed" in record.message for record in caplog.records)


class TestStorageFailure:
    async def test_upload_profile_picture_disk_write_failure_propagates(
        self, db_session: AsyncSession, storage_service, monkeypatch
    ):
        from app.tests.factories import UserFactory

        user = UserFactory(username="diskfail", email="diskfail@example.com")
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)

        async def broken_save(content: bytes) -> str:
            raise OSError("disk full")

        monkeypatch.setattr(storage_service, "save_profile_image", broken_save)
        monkeypatch.setattr(user_service, "local_storage", storage_service)

        class FakeUploadFile:
            async def read(self) -> bytes:
                return b"not-checked"

        with pytest.raises(OSError):
            await user_service.upload_profile_picture(
                db_session, user.id, user, FakeUploadFile()
            )

    async def test_upload_profile_picture_corrupt_image_returns_bad_request(
        self, db_session: AsyncSession, storage_service, monkeypatch
    ):
        from app.exceptions.base import BadRequestError
        from app.tests.factories import UserFactory

        user = UserFactory(username="corruptimg", email="corruptimg@example.com")
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)

        monkeypatch.setattr(user_service, "local_storage", storage_service)

        class FakeUploadFile:
            async def read(self) -> bytes:
                return b"not-a-real-image"

        with pytest.raises(BadRequestError):
            await user_service.upload_profile_picture(
                db_session, user.id, user, FakeUploadFile()
            )


class TestSMTPFailure:
    async def test_send_verification_email_propagates_smtp_error(
        self, client: AsyncClient, monkeypatch
    ):
        async def broken_send(*args, **kwargs):
            raise aiosmtplib.SMTPConnectError("smtp unreachable")

        monkeypatch.setattr("aiosmtplib.send", broken_send)

        with pytest.raises(aiosmtplib.SMTPConnectError):
            await client.post(
                "/api/v1/users",
                json={
                    "username": "smtpfail",
                    "email": "smtpfail@example.com",
                    "password": "testpassword123",
                },
            )

    async def test_send_password_reset_email_propagates_smtp_error(
        self, client: AsyncClient, db_session: AsyncSession, monkeypatch
    ):
        await create_test_user(client, db_session, "smtpfail2", "smtpfail2@example.com")

        async def broken_send(*args, **kwargs):
            raise aiosmtplib.SMTPConnectError("smtp unreachable")

        monkeypatch.setattr("aiosmtplib.send", broken_send)

        with pytest.raises(aiosmtplib.SMTPConnectError):
            await client.post(
                "/api/v1/users/forgot-password", json={"email": "smtpfail2@example.com"}
            )


class TestDatabaseFailure:
    async def test_list_posts_unhandled_db_error_returns_500(
        self, db_session: AsyncSession, mocked_redis
    ):
        class BrokenSession:
            async def execute(self, *args, **kwargs):
                raise RuntimeError("db down")

        async def override_get_db():
            yield BrokenSession()

        app.dependency_overrides[get_db] = override_get_db
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app, raise_app_exceptions=False),
                base_url="http://test",
            ) as ac:
                response = await ac.get("/api/v1/posts")
        finally:
            app.dependency_overrides.clear()

        # No global handler for raw DB errors exists (only /ready degrades to 503);
        # current actual behavior on a regular endpoint is an unhandled 500.
        assert response.status_code == 500
