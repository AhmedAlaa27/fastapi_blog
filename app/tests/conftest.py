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

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import User
from app.models.role import Permission, Role

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
    yield fake
    await fake.aclose()


@pytest.fixture
async def client(
    db_session: AsyncSession,
    mocked_aws,
    mocked_redis,
) -> AsyncGenerator[AsyncClient]:

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac

    app.dependency_overrides.clear()


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
