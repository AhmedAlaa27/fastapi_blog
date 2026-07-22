import os
from collections.abc import AsyncGenerator

# Test DB and Bucket
os.environ["DATABASE_URL"] = (
    "postgresql+psycopg://bloguser:blogpass@localhost/test_blog"
)
os.environ["S3_BUCKET_NAME"] = "test-bucket"
os.environ["SECRET_KEY"] = "test-secret-key-for-testing-only"


# Dummy S3/AWS Credentials
os.environ["S3_ACCESS_KEY_ID"] = "testing"
os.environ["S3_SECRET_ACCESS_KEY"] = "testing"
os.environ["S3_REGION"] = "us-east-1"

os.environ["AWS_ACCESS_KEY_ID"] = "testing"
os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
os.environ["AWS_DEFAULT_REGION"] = "us-east-1"


import boto3
import fakeredis.aioredis
import pytest
from httpx import ASGITransport, AsyncClient
from moto import mock_aws
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.db.base import Base
from app.db.session import get_db
from app.infrastructure.cache.redis_cache_service import RedisCacheService
from app.main import app
from app.models import User
from app.models.role import Permission, Role
from app.storage.local_storage import LocalStorage
import app.storage.local_storage as local_storage_module

pytest_plugins = ["anyio"]

PERMISSIONS = ["posts:create", "posts:update", "posts:delete"]
ROLE_PERMISSIONS = {
    "admin": ["posts:create", "posts:update", "posts:delete"],
    "author": ["posts:create"],
}


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest.fixture(scope="session")
def test_engine():
    engine = create_async_engine(
        os.environ["DATABASE_URL"],
        poolclass=NullPool,
    )
    return engine


@pytest.fixture(scope="session")
async def setup_database(test_engine):
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    seed_session = async_sessionmaker(bind=test_engine, expire_on_commit=False)()
    async with seed_session as session:
        permissions = {name: Permission(name=name) for name in PERMISSIONS}
        session.add_all(permissions.values())
        for role_name, perm_names in ROLE_PERMISSIONS.items():
            session.add(
                Role(
                    name=role_name,
                    permissions=[permissions[name] for name in perm_names],
                )
            )
        await session.commit()

    yield

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await test_engine.dispose()


@pytest.fixture
async def db_session(
    test_engine,
    setup_database,
) -> AsyncGenerator[AsyncSession]:
    conn = await test_engine.connect()
    trans = await conn.begin()

    test_async_session = async_sessionmaker(
        bind=conn,
        class_=AsyncSession,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )

    async with test_async_session() as session:
        try:
            yield session
        finally:
            await session.close()
            await trans.rollback()
            await conn.close()


@pytest.fixture
def mocked_aws():
    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket=os.environ["S3_BUCKET_NAME"])
        yield s3


@pytest.fixture
async def mocked_redis(monkeypatch):
    fake = fakeredis.aioredis.FakeRedis(decode_responses=True)

    async def _get_fake_client():
        return fake

    monkeypatch.setattr("app.infrastructure.cache.client.get_redis_client", _get_fake_client)
    # redis_cache_service.py does `from ... import get_redis_client`, binding its own
    # module-level name at import time; patching client.py alone doesn't reach it.
    monkeypatch.setattr(
        "app.infrastructure.cache.redis_cache_service.get_redis_client", _get_fake_client
    )
    yield fake
    await fake.aclose()


@pytest.fixture
async def client(
    db_session: AsyncSession,
    mocked_aws,
    mocked_redis,
    monkeypatch,
) -> AsyncGenerator[AsyncClient]:
    # slowapi's Limiter connects directly to settings.redis_url (real Redis), independent
    # of the mocked_redis patch above. Flush it so per-test rate limits (5/min login,
    # 5/hour register, etc.) don't accumulate real state across test runs.
    import redis.asyncio as real_redis

    rate_limit_client = real_redis.from_url(settings.redis_url)
    await rate_limit_client.flushdb()
    await rate_limit_client.aclose()

    # register()/forgot_password() queue a real email via BackgroundTasks, which run
    # inline under ASGITransport. Default to a no-op so tests don't hit the real SMTP
    # server configured in .env; tests exercising SMTP failure override this.
    async def _noop_send_email(*args, **kwargs) -> None:
        return None

    monkeypatch.setattr("aiosmtplib.send", _noop_send_email)

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest.fixture
async def redis_client(mocked_redis):
    return mocked_redis


@pytest.fixture
def cache_service(mocked_redis) -> RedisCacheService:
    return RedisCacheService()


@pytest.fixture
def storage_service(tmp_path, monkeypatch) -> LocalStorage:
    monkeypatch.setattr(local_storage_module, "PROFILE_PICS_DIR", tmp_path)
    return LocalStorage()


@pytest.fixture
async def anonymous_client(client: AsyncClient) -> AsyncClient:
    return client


@pytest.fixture
async def author_client(
    client: AsyncClient, db_session: AsyncSession
) -> AsyncGenerator[AsyncClient]:
    # A separate AsyncClient instance (not the shared `client`) so its Authorization
    # header doesn't collide with sibling fixtures like admin_client in the same test;
    # `client`'s dependency_overrides on `app` stay active for both.
    await create_test_user(
        client, db_session, "author_user", "author_user@example.com", "testpassword123"
    )
    token = await login_user(client, "author_user@example.com", "testpassword123")
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers=auth_header(token),
    ) as ac:
        yield ac


@pytest.fixture
async def admin_client(
    client: AsyncClient, db_session: AsyncSession
) -> AsyncGenerator[AsyncClient]:
    await create_test_user(
        client, db_session, "admin_user", "admin_user@example.com", "testpassword123"
    )
    # Eager-load roles before assigning a new collection: SQLAlchemy needs to read the
    # existing collection to diff it, and a lazy load can't run in this async context.
    result = await db_session.execute(
        select(User)
        .options(selectinload(User.roles))
        .where(User.email == "admin_user@example.com")
    )
    user = result.scalars().one()
    role_result = await db_session.execute(select(Role).where(Role.name == "admin"))
    user.roles = [role_result.scalars().one()]
    await db_session.commit()

    token = await login_user(client, "admin_user@example.com", "testpassword123")
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers=auth_header(token),
    ) as ac:
        yield ac


async def create_test_user(
    client: AsyncClient,
    db_session: AsyncSession,
    username: str = "testuser",
    email: str = "test@example.com",
    password: str = "testpassword123",
) -> dict:
    response = await client.post(
        "/api/v1/users",
        json={
            "username": username,
            "email": email,
            "password": password,
        },
    )
    assert response.status_code == 201, f"Failed to create user: {response.text}"

    # Registration requires email verification before login; tests bypass
    # the email round-trip by flipping the flag directly.
    result = await db_session.execute(select(User).where(User.email == email.lower()))
    user = result.scalars().one()
    user.email_verified = True
    await db_session.commit()

    return response.json()


async def login_user(
    client: AsyncClient,
    email: str = "test@example.com",
    password: str = "testpassword123",
) -> str:
    response = await client.post(
        "/api/v1/users/token",
        data={
            "username": email,
            "password": password,
        },
    )
    assert response.status_code == 200, f"Failed to login: {response.text}"
    return response.json()["access_token"]


def auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
