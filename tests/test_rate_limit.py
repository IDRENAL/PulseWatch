"""Тесты на rate limiter (slowapi) для /auth эндпоинтов."""

import pytest_asyncio
from httpx import AsyncClient

from app.core.rate_limit import limiter


@pytest_asyncio.fixture
async def enabled_limiter():
    """Включает лимитер для теста и сбрасывает счётчики до и после."""
    limiter.reset()
    limiter.enabled = True
    yield
    limiter.enabled = False
    limiter.reset()


async def test_login_rate_limit(client: AsyncClient, enabled_limiter):
    """6-й логин подряд возвращает 429."""
    await client.post(
        "/auth/register",
        json={"email": "alice@example.com", "password": "secret123"},
    )

    for _ in range(5):
        r = await client.post(
            "/auth/login",
            data={"username": "alice@example.com", "password": "secret123"},
        )
        assert r.status_code == 200

    r = await client.post(
        "/auth/login",
        data={"username": "alice@example.com", "password": "secret123"},
    )
    assert r.status_code == 429


async def test_register_rate_limit(client: AsyncClient, enabled_limiter):
    """4-я регистрация подряд возвращает 429."""
    for i in range(3):
        r = await client.post(
            "/auth/register",
            json={"email": f"user{i}@example.com", "password": "secret123"},
        )
        assert r.status_code == 201

    r = await client.post(
        "/auth/register",
        json={"email": "user4@example.com", "password": "secret123"},
    )
    assert r.status_code == 429
