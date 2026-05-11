import asyncio

import asyncpg
import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings
from app.core.rate_limit import limiter
from app.database import Base, get_db
from app.main import app
from app.models.alert_event import AlertEvent  # noqa: F401
from app.models.alert_rule import AlertRule  # noqa: F401
from app.models.docker_aggregate import DockerAggregate  # noqa: F401
from app.models.docker_metric import DockerMetric  # noqa: F401
from app.models.metric import Metric  # noqa: F401
from app.models.metric_aggregate import MetricAggregate  # noqa: F401
from app.models.server import Server  # noqa: F401
from app.models.user import User  # noqa: F401  -- регистрирует таблицу в Base.metadata
from app.redis_client import set_redis_client

# Rate limiter отключён глобально для тестов, иначе 4-я регистрация в одном
# тесте или 6-й логин ловят 429 и валят сценарий. Тесты на сам лимитер
# включают его обратно через свою фикстуру.
limiter.enabled = False

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
        exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", TEST_DB_NAME)
        if not exists:
            await conn.execute(f'CREATE DATABASE "{TEST_DB_NAME}"')
    finally:
        await conn.close()


@pytest_asyncio.fixture(scope="session")
async def test_redis_session():
    """Сессионный Redis-клиент. ASGITransport не запускает lifespan FastAPI,
    поэтому глобальный клиент приложения не инициализируется автоматически.
    """
    client = Redis.from_url(settings.redis_url, decode_responses=True)
    await client.ping()  # type: ignore[misc]
    yield client
    await client.aclose()


@pytest_asyncio.fixture(autouse=True)
async def _bind_redis_per_test(test_redis_session):
    """Тесты Celery-задач (notification_tasks) в своём `finally` зовут
    set_redis_client(None) — это обнуляет глобал между тестами и валит
    последующие, которые ждут реальный Redis. Перевыставляем перед каждым.

    Заодно чистим Redis — dashboard-кэш и whitelist refresh-токенов протекают
    между тестами и валят те, что зависят от чистого DB-состояния.
    """
    await test_redis_session.flushdb()
    set_redis_client(test_redis_session)
    yield


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


@pytest_asyncio.fixture
async def db_session(test_engine):
    """Реальная асинхронная сессия БД для прямых вызовов сервисного слоя."""
    test_session_maker = async_sessionmaker(test_engine, expire_on_commit=False)
    async with test_session_maker() as session:
        yield session
