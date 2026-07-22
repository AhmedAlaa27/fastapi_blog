from io import BytesIO

import pytest
from httpx import AsyncClient
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import audit_service
from app.tests.conftest import auth_header, create_test_user, login_user

pytestmark = pytest.mark.anyio


def _spy_audit_log(monkeypatch):
    calls = []
    original = audit_service.log_event

    async def spy(db, **kwargs):
        calls.append(kwargs)
        return await original(db, **kwargs)

    monkeypatch.setattr(audit_service, "log_event", spy)
    return calls


class TestPostsAPI:
    async def test_get_posts_list_returns_paginated_shape(self, client: AsyncClient):
        response = await client.get("/api/v1/posts")
        assert response.status_code == 200
        body = response.json()
        assert set(body.keys()) == {"posts", "total", "skip", "limit", "has_more"}

    async def test_create_post_returns_201_and_serializes_author(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        await create_test_user(client, db_session, "poster", "poster@example.com")
        token = await login_user(client, "poster@example.com", "testpassword123")
        response = await client.post(
            "/api/v1/posts",
            json={"title": "Hello", "content": "World"},
            headers=auth_header(token),
        )
        assert response.status_code == 201
        body = response.json()
        assert body["title"] == "Hello"
        assert body["author"]["username"] == "poster"

    async def test_create_post_validation_error_returns_422(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        await create_test_user(client, db_session, "poster2", "poster2@example.com")
        token = await login_user(client, "poster2@example.com", "testpassword123")
        response = await client.post(
            "/api/v1/posts", json={"title": "", "content": "x"}, headers=auth_header(token)
        )
        assert response.status_code == 422

    async def test_create_post_logs_audit_event(
        self, client: AsyncClient, db_session: AsyncSession, monkeypatch
    ):
        await create_test_user(client, db_session, "auditposter", "auditposter@example.com")
        token = await login_user(client, "auditposter@example.com", "testpassword123")
        calls = _spy_audit_log(monkeypatch)
        response = await client.post(
            "/api/v1/posts",
            json={"title": "Audited", "content": "content"},
            headers=auth_header(token),
        )
        post_id = response.json()["id"]

        assert len(calls) == 1
        assert calls[0]["action"] == "create"
        assert calls[0]["resource"] == "post"
        assert calls[0]["resource_id"] == post_id

    async def test_update_post_logs_audit_event(
        self, client: AsyncClient, db_session: AsyncSession, monkeypatch
    ):
        await create_test_user(client, db_session, "updater", "updater@example.com")
        token = await login_user(client, "updater@example.com", "testpassword123")
        create_response = await client.post(
            "/api/v1/posts",
            json={"title": "Before", "content": "content"},
            headers=auth_header(token),
        )
        post_id = create_response.json()["id"]

        calls = _spy_audit_log(monkeypatch)
        response = await client.put(
            f"/api/v1/posts/{post_id}",
            json={"title": "After", "content": "content"},
            headers=auth_header(token),
        )
        assert response.status_code == 200
        assert calls[0]["action"] == "update"
        assert calls[0]["resource_id"] == post_id

    async def test_delete_post_logs_audit_event(
        self, client: AsyncClient, db_session: AsyncSession, monkeypatch
    ):
        await create_test_user(client, db_session, "deleter2", "deleter2@example.com")
        token = await login_user(client, "deleter2@example.com", "testpassword123")
        create_response = await client.post(
            "/api/v1/posts",
            json={"title": "Bye", "content": "content"},
            headers=auth_header(token),
        )
        post_id = create_response.json()["id"]

        calls = _spy_audit_log(monkeypatch)
        response = await client.delete(
            f"/api/v1/posts/{post_id}", headers=auth_header(token)
        )
        assert response.status_code == 204
        assert calls[0]["action"] == "delete"
        assert calls[0]["resource_id"] == post_id


class TestUsersAPI:
    async def test_get_user_by_id_returns_public_shape(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user_data = await create_test_user(client, db_session, "pubuser", "pubuser@example.com")
        response = await client.get(f"/api/v1/users/{user_data['id']}")
        assert response.status_code == 200
        body = response.json()
        assert set(body.keys()) == {"id", "username", "image_file", "image_path"}

    async def test_get_user_missing_returns_404(self, client: AsyncClient):
        response = await client.get("/api/v1/users/999999")
        assert response.status_code == 404

    async def test_patch_user_updates_username(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user_data = await create_test_user(client, db_session, "patchme", "patchme@example.com")
        token = await login_user(client, "patchme@example.com", "testpassword123")
        response = await client.patch(
            f"/api/v1/users/{user_data['id']}",
            json={"username": "patched"},
            headers=auth_header(token),
        )
        assert response.status_code == 200
        assert response.json()["username"] == "patched"

    async def test_patch_user_denies_non_owner(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        victim = await create_test_user(client, db_session, "patchvictim", "patchvictim@example.com")
        await create_test_user(client, db_session, "patchattacker", "patchattacker@example.com")
        attacker_token = await login_user(client, "patchattacker@example.com", "testpassword123")

        response = await client.patch(
            f"/api/v1/users/{victim['id']}",
            json={"username": "hijacked"},
            headers=auth_header(attacker_token),
        )
        assert response.status_code == 403

    async def test_delete_user_logs_audit_event(
        self, client: AsyncClient, db_session: AsyncSession, monkeypatch
    ):
        user_data = await create_test_user(
            client, db_session, "deleteuser", "deleteuser@example.com"
        )
        token = await login_user(client, "deleteuser@example.com", "testpassword123")

        calls = _spy_audit_log(monkeypatch)
        response = await client.delete(
            f"/api/v1/users/{user_data['id']}", headers=auth_header(token)
        )
        assert response.status_code == 204
        assert calls[0]["action"] == "delete"
        assert calls[0]["resource"] == "user"

    async def test_get_user_posts_paginated(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user_data = await create_test_user(client, db_session, "poster3", "poster3@example.com")
        token = await login_user(client, "poster3@example.com", "testpassword123")
        await client.post(
            "/api/v1/posts", json={"title": "P1", "content": "c"}, headers=auth_header(token)
        )

        response = await client.get(f"/api/v1/users/{user_data['id']}/posts")
        assert response.status_code == 200
        assert response.json()["total"] == 1

    async def test_upload_profile_picture_returns_updated_user(
        self, client: AsyncClient, db_session: AsyncSession, storage_service, monkeypatch
    ):
        import app.services.user_service as user_service_module

        monkeypatch.setattr(user_service_module, "local_storage", storage_service)

        user_data = await create_test_user(client, db_session, "picapi", "picapi@example.com")
        token = await login_user(client, "picapi@example.com", "testpassword123")

        buf = BytesIO()
        Image.new("RGB", (10, 10), color="blue").save(buf, format="JPEG")
        buf.seek(0)

        response = await client.patch(
            f"/api/v1/users/{user_data['id']}/picture",
            files={"file": ("pic.jpg", buf, "image/jpeg")},
            headers=auth_header(token),
        )
        assert response.status_code == 200
        assert response.json()["image_file"] is not None

    async def test_delete_profile_picture_with_none_returns_404(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user_data = await create_test_user(client, db_session, "nopicapi", "nopicapi@example.com")
        token = await login_user(client, "nopicapi@example.com", "testpassword123")

        response = await client.delete(
            f"/api/v1/users/{user_data['id']}/picture", headers=auth_header(token)
        )
        assert response.status_code == 404


class TestAuthAPIAudit:
    async def test_register_logs_audit_event(self, client: AsyncClient, monkeypatch):
        calls = _spy_audit_log(monkeypatch)
        response = await client.post(
            "/api/v1/users",
            json={
                "username": "auditreg",
                "email": "auditreg@example.com",
                "password": "testpassword123",
            },
        )
        assert response.status_code == 201
        assert calls[0]["action"] == "register"

    async def test_login_logs_audit_event(
        self, client: AsyncClient, db_session: AsyncSession, monkeypatch
    ):
        await create_test_user(client, db_session, "auditlogin", "auditlogin@example.com")
        calls = _spy_audit_log(monkeypatch)
        response = await client.post(
            "/api/v1/users/token",
            data={"username": "auditlogin@example.com", "password": "testpassword123"},
        )
        assert response.status_code == 200
        assert calls[0]["action"] == "login"


class TestRateLimiting:
    async def test_login_rate_limit_returns_429_after_exceeding(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        await create_test_user(client, db_session, "ratelimited", "ratelimited@example.com")

        statuses = []
        for _ in range(6):
            response = await client.post(
                "/api/v1/users/token",
                data={"username": "ratelimited@example.com", "password": "wrongpassword"},
            )
            statuses.append(response.status_code)

        assert statuses[:5] == [401, 401, 401, 401, 401]
        assert statuses[5] == 429

    async def test_register_rate_limit_returns_429_after_exceeding(
        self, client: AsyncClient
    ):
        statuses = []
        for i in range(6):
            response = await client.post(
                "/api/v1/users",
                json={
                    "username": f"burst{i}",
                    "email": f"burst{i}@example.com",
                    "password": "testpassword123",
                },
            )
            statuses.append(response.status_code)

        assert statuses[:5] == [201, 201, 201, 201, 201]
        assert statuses[5] == 429
