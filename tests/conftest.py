import asyncio

import asyncpg
import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings
from app.database import Base, get_db
from app.main import app
from app.models.user import User  # noqa: F401  -- регистрирует таблицу в Base.metadata
from app.models.server import Server  # noqa: F401
from app.models.metric import Metric  # noqa: F401
from app.models.docker_metric import DockerMetric  # noqa: F401

TEST_DB_NAME = "pulsewatch_test"
TEST_DB_URL = (
    f"postgresql+asyncpg://{settings.db_user}:{settings.db_password}"
    f"@{settings.db_host}:{settings.db_port}/{TEST_DB_NAME}"
)
ADMIN_DB_URL = (
    f"postgresql://{settings.db_user}:{settings.db_password}"
    f"@{settings.db_host}:{settings.db_port}/postgres"
)


async def _ensure_test_db_exists() -> None:
    conn = await asyncpg.connect(ADMIN_DB_URL)
    try:
        exists = await conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", TEST_DB_NAME
        )
        if not exists:
            await conn.execute(f'CREATE DATABASE "{TEST_DB_NAME}"')
    finally:
        await conn.close()


@pytest_asyncio.fixture(scope="session")
async def test_engine():
    await _ensure_test_db_exists()
    engine = create_async_engine(TEST_DB_URL, echo=False, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def client(test_engine):
    # Перед каждым тестом — чистая БД.
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    test_session_maker = async_sessionmaker(test_engine, expire_on_commit=False)

    async def override_get_db():
        async with test_session_maker() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest.fixture
def sync_client(test_engine):
    """Sync TestClient для WS-тестов (наш AsyncClient WS не поддерживает)."""
    async def _reset_db():
        async with test_engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_reset_db())

    test_session_maker = async_sessionmaker(test_engine, expire_on_commit=False)

    async def override_get_db():
        async with test_session_maker() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as tc:
        yield tc

    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def auth_headers(client: AsyncClient):
    """Регистрирует юзера alice и возвращает заголовок с её JWT."""
    await client.post(
        "/auth/register",
        json={"email": "alice@example.com", "password": "secret123"},
    )
    response = await client.post(
        "/auth/login",
        data={"username": "alice@example.com", "password": "secret123"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
