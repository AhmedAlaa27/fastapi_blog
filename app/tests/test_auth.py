from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import (
    create_refresh_token,
    generate_reset_token,
    hash_reset_token,
)
from app.models import EmailVerificationToken, PasswordResetToken, Post, RefreshToken, User
from app.tests.conftest import auth_header, create_test_user, login_user

pytestmark = pytest.mark.anyio


class TestLogin:
    async def test_valid_credentials_returns_token_pair(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        await create_test_user(client, db_session, "loginuser", "loginuser@example.com")
        response = await client.post(
            "/api/v1/users/token",
            data={"username": "loginuser@example.com", "password": "testpassword123"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["access_token"]
        assert body["refresh_token"]
        assert body["token_type"] == "bearer"

    async def test_wrong_password_returns_401(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        await create_test_user(client, db_session, "wrongpw", "wrongpw@example.com")
        response = await client.post(
            "/api/v1/users/token",
            data={"username": "wrongpw@example.com", "password": "wrongpassword"},
        )
        assert response.status_code == 401

    async def test_unknown_email_returns_401(self, client: AsyncClient):
        response = await client.post(
            "/api/v1/users/token",
            data={"username": "nobody@example.com", "password": "whatever123"},
        )
        assert response.status_code == 401

    async def test_unverified_email_returns_403(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        response = await client.post(
            "/api/v1/users",
            json={
                "username": "unverified",
                "email": "unverified@example.com",
                "password": "testpassword123",
            },
        )
        assert response.status_code == 201

        login_response = await client.post(
            "/api/v1/users/token",
            data={"username": "unverified@example.com", "password": "testpassword123"},
        )
        assert login_response.status_code == 403


class TestRefresh:
    async def test_valid_refresh_rotates_token(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        await create_test_user(client, db_session, "refresher", "refresher@example.com")
        login_response = await client.post(
            "/api/v1/users/token",
            data={"username": "refresher@example.com", "password": "testpassword123"},
        )
        refresh_token = login_response.json()["refresh_token"]

        response = await client.post(
            "/api/v1/users/refresh", json={"refresh_token": refresh_token}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["refresh_token"] != refresh_token

    async def test_reused_refresh_token_returns_401(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        await create_test_user(client, db_session, "reuser2", "reuser2@example.com")
        login_response = await client.post(
            "/api/v1/users/token",
            data={"username": "reuser2@example.com", "password": "testpassword123"},
        )
        refresh_token = login_response.json()["refresh_token"]

        first = await client.post(
            "/api/v1/users/refresh", json={"refresh_token": refresh_token}
        )
        assert first.status_code == 200

        second = await client.post(
            "/api/v1/users/refresh", json={"refresh_token": refresh_token}
        )
        assert second.status_code == 401

    async def test_expired_refresh_token_returns_401(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user_data = await create_test_user(
            client, db_session, "expireduser", "expireduser@example.com"
        )
        raw_token = create_refresh_token(user_data["id"])
        db_session.add(
            RefreshToken(
                user_id=user_data["id"],
                token_hash=hash_reset_token(raw_token),
                expires_at=datetime.now(UTC) - timedelta(days=1),
            )
        )
        await db_session.commit()

        response = await client.post(
            "/api/v1/users/refresh", json={"refresh_token": raw_token}
        )
        assert response.status_code == 401

    async def test_malformed_refresh_token_returns_401(self, client: AsyncClient):
        response = await client.post(
            "/api/v1/users/refresh", json={"refresh_token": "not-a-real-jwt"}
        )
        assert response.status_code == 401


class TestEmailVerification:
    async def test_valid_token_verifies_email(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        response = await client.post(
            "/api/v1/users",
            json={
                "username": "verifyme",
                "email": "verifyme@example.com",
                "password": "testpassword123",
            },
        )
        user_id = response.json()["id"]

        raw_token = generate_reset_token()
        result = await db_session.execute(
            select(EmailVerificationToken).where(
                EmailVerificationToken.user_id == user_id
            )
        )
        stored = result.scalars().one()
        stored.token_hash = hash_reset_token(raw_token)
        await db_session.commit()

        verify_response = await client.post(
            "/api/v1/users/verify-email", json={"token": raw_token}
        )
        assert verify_response.status_code == 200

        refreshed = await db_session.execute(select(User).where(User.id == user_id))
        assert refreshed.scalars().one().email_verified is True

    async def test_expired_token_returns_400(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        response = await client.post(
            "/api/v1/users",
            json={
                "username": "expiredverify",
                "email": "expiredverify@example.com",
                "password": "testpassword123",
            },
        )
        user_id = response.json()["id"]

        raw_token = generate_reset_token()
        result = await db_session.execute(
            select(EmailVerificationToken).where(
                EmailVerificationToken.user_id == user_id
            )
        )
        stored = result.scalars().one()
        stored.token_hash = hash_reset_token(raw_token)
        stored.expires_at = datetime.now(UTC) - timedelta(hours=1)
        await db_session.commit()

        verify_response = await client.post(
            "/api/v1/users/verify-email", json={"token": raw_token}
        )
        assert verify_response.status_code == 400

    async def test_reverifying_deleted_token_returns_400(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        response = await client.post(
            "/api/v1/users/verify-email", json={"token": "never-issued"}
        )
        assert response.status_code == 400


class TestPasswordReset:
    async def test_forgot_password_always_returns_202(self, client: AsyncClient):
        response = await client.post(
            "/api/v1/users/forgot-password", json={"email": "nobody@example.com"}
        )
        assert response.status_code == 202

    async def test_reset_password_valid_token(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user_data = await create_test_user(
            client, db_session, "resetme", "resetme@example.com"
        )
        raw_token = generate_reset_token()
        db_session.add(
            PasswordResetToken(
                user_id=user_data["id"],
                token_hash=hash_reset_token(raw_token),
                expires_at=datetime.now(UTC) + timedelta(minutes=60),
            )
        )
        await db_session.commit()

        response = await client.post(
            "/api/v1/users/reset-password",
            json={"token": raw_token, "new_password": "newpassword456"},
        )
        assert response.status_code == 200

        login_response = await client.post(
            "/api/v1/users/token",
            data={"username": "resetme@example.com", "password": "newpassword456"},
        )
        assert login_response.status_code == 200

    async def test_reset_password_expired_token_returns_400(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user_data = await create_test_user(
            client, db_session, "resetexpired", "resetexpired@example.com"
        )
        raw_token = generate_reset_token()
        db_session.add(
            PasswordResetToken(
                user_id=user_data["id"],
                token_hash=hash_reset_token(raw_token),
                expires_at=datetime.now(UTC) - timedelta(minutes=1),
            )
        )
        await db_session.commit()

        response = await client.post(
            "/api/v1/users/reset-password",
            json={"token": raw_token, "new_password": "newpassword456"},
        )
        assert response.status_code == 400

    async def test_reset_password_invalid_token_returns_400(self, client: AsyncClient):
        response = await client.post(
            "/api/v1/users/reset-password",
            json={"token": "bogus", "new_password": "newpassword456"},
        )
        assert response.status_code == 400

    async def test_reset_password_revokes_refresh_tokens(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user_data = await create_test_user(
            client, db_session, "resetrevoke", "resetrevoke@example.com"
        )
        login_response = await client.post(
            "/api/v1/users/token",
            data={"username": "resetrevoke@example.com", "password": "testpassword123"},
        )
        old_refresh_token = login_response.json()["refresh_token"]

        raw_reset_token = generate_reset_token()
        db_session.add(
            PasswordResetToken(
                user_id=user_data["id"],
                token_hash=hash_reset_token(raw_reset_token),
                expires_at=datetime.now(UTC) + timedelta(minutes=60),
            )
        )
        await db_session.commit()

        await client.post(
            "/api/v1/users/reset-password",
            json={"token": raw_reset_token, "new_password": "newpassword456"},
        )

        refresh_response = await client.post(
            "/api/v1/users/refresh", json={"refresh_token": old_refresh_token}
        )
        assert refresh_response.status_code == 401


class TestChangePassword:
    async def test_valid_current_password_changes_it(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        await create_test_user(client, db_session, "changepw", "changepw@example.com")
        token = await login_user(client, "changepw@example.com", "testpassword123")

        response = await client.patch(
            "/api/v1/users/me/password",
            json={"current_password": "testpassword123", "new_password": "brandnew456"},
            headers=auth_header(token),
        )
        assert response.status_code == 200

        login_response = await client.post(
            "/api/v1/users/token",
            data={"username": "changepw@example.com", "password": "brandnew456"},
        )
        assert login_response.status_code == 200

    async def test_wrong_current_password_returns_400(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        await create_test_user(client, db_session, "changepw2", "changepw2@example.com")
        token = await login_user(client, "changepw2@example.com", "testpassword123")

        response = await client.patch(
            "/api/v1/users/me/password",
            json={"current_password": "wrongpassword", "new_password": "brandnew456"},
            headers=auth_header(token),
        )
        assert response.status_code == 400


class TestRBAC:
    async def test_admin_can_delete_others_post(
        self, admin_client: AsyncClient, author_client: AsyncClient, db_session: AsyncSession
    ):
        create_response = await author_client.post(
            "/api/v1/posts", json={"title": "Author post", "content": "content"}
        )
        assert create_response.status_code == 201
        post_id = create_response.json()["id"]

        delete_response = await admin_client.delete(f"/api/v1/posts/{post_id}")
        assert delete_response.status_code == 204

    async def test_author_forbidden_to_delete_others_post(
        self, admin_client: AsyncClient, author_client: AsyncClient, db_session: AsyncSession
    ):
        create_response = await admin_client.post(
            "/api/v1/posts", json={"title": "Admin post", "content": "content"}
        )
        assert create_response.status_code == 201
        post_id = create_response.json()["id"]

        delete_response = await author_client.delete(f"/api/v1/posts/{post_id}")
        assert delete_response.status_code == 403

    async def test_anonymous_forbidden_to_create_post(self, anonymous_client: AsyncClient):
        response = await anonymous_client.post(
            "/api/v1/posts", json={"title": "Anon post", "content": "content"}
        )
        assert response.status_code == 401


class TestOwnership:
    async def test_owner_can_update_own_post(self, author_client: AsyncClient):
        create_response = await author_client.post(
            "/api/v1/posts", json={"title": "Mine", "content": "original"}
        )
        post_id = create_response.json()["id"]

        response = await author_client.put(
            f"/api/v1/posts/{post_id}", json={"title": "Updated", "content": "updated"}
        )
        assert response.status_code == 200
        assert response.json()["title"] == "Updated"

    async def test_non_owner_without_permission_forbidden(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        author_data = await create_test_user(
            client, db_session, "postowner", "postowner@example.com"
        )
        post = Post(title="Owned", content="content", user_id=author_data["id"])
        db_session.add(post)
        await db_session.commit()
        await db_session.refresh(post)

        await create_test_user(client, db_session, "intruder", "intruder@example.com")
        intruder_token = await login_user(client, "intruder@example.com", "testpassword123")

        response = await client.put(
            f"/api/v1/posts/{post.id}",
            json={"title": "Hijacked", "content": "hijacked"},
            headers=auth_header(intruder_token),
        )
        assert response.status_code == 403


class TestGoogleOAuth:
    async def test_new_google_account_creates_user(
        self, client: AsyncClient, monkeypatch
    ):
        def fake_verify(id_token_str, request, client_id):
            return {"sub": "google-sub-123", "email": "newgoogle@example.com"}

        monkeypatch.setattr(
            "app.services.auth_service.google_id_token.verify_oauth2_token", fake_verify
        )

        response = await client.post(
            "/api/v1/users/oauth/google", json={"id_token": "fake-token"}
        )
        assert response.status_code == 200
        assert response.json()["access_token"]

    async def test_existing_google_account_signs_in(
        self, client: AsyncClient, db_session: AsyncSession, monkeypatch
    ):
        def fake_verify(id_token_str, request, client_id):
            return {"sub": "google-sub-existing", "email": "existinggoogle@example.com"}

        monkeypatch.setattr(
            "app.services.auth_service.google_id_token.verify_oauth2_token", fake_verify
        )

        first = await client.post(
            "/api/v1/users/oauth/google", json={"id_token": "fake-token"}
        )
        second = await client.post(
            "/api/v1/users/oauth/google", json={"id_token": "fake-token"}
        )
        assert first.status_code == 200
        assert second.status_code == 200

        result = await db_session.execute(
            select(User).where(User.oauth_sub == "google-sub-existing")
        )
        assert len(result.scalars().all()) == 1

    async def test_local_account_auto_linked_by_email(
        self, client: AsyncClient, db_session: AsyncSession, monkeypatch
    ):
        await create_test_user(client, db_session, "linkme", "linkme@example.com")

        def fake_verify(id_token_str, request, client_id):
            return {"sub": "google-sub-linked", "email": "linkme@example.com"}

        monkeypatch.setattr(
            "app.services.auth_service.google_id_token.verify_oauth2_token", fake_verify
        )

        response = await client.post(
            "/api/v1/users/oauth/google", json={"id_token": "fake-token"}
        )
        assert response.status_code == 200

        result = await db_session.execute(
            select(User).where(User.email == "linkme@example.com")
        )
        assert result.scalars().one().oauth_sub == "google-sub-linked"

    async def test_invalid_google_token_returns_401(
        self, client: AsyncClient, monkeypatch
    ):
        def fake_verify(id_token_str, request, client_id):
            raise ValueError("invalid token")

        monkeypatch.setattr(
            "app.services.auth_service.google_id_token.verify_oauth2_token", fake_verify
        )

        response = await client.post(
            "/api/v1/users/oauth/google", json={"id_token": "bad-token"}
        )
        assert response.status_code == 401
