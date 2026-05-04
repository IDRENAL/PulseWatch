"""Тесты API агрегированных метрик."""
from datetime import datetime, timedelta, timezone

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.metric_aggregate import PeriodType
from app.services.aggregation import (
    aggregate_system_metrics,
    aggregate_docker_metrics,
)


@pytest_asyncio.fixture
async def server_with_key(
    client: AsyncClient, auth_headers: dict[str, str]
) -> dict:
    """Создаёт сервер и возвращает его данные с api_key."""
    response = await client.post(
        "/servers/register",
        json={"name": "web-prod-01"},
        headers=auth_headers,
    )
    assert response.status_code == 201
    return response.json()


def _container_payload(name: str = "pulsewatch_db", **overrides) -> dict:
    """Вспомогательная функция для формирования payload docker-метрик."""
    base = {
        "container_id": "abc123def456",
        "container_name": name,
        "image": "postgres:16-alpine",
        "status": "running",
        "cpu_percent": 5.0,
        "memory_usage_mb": 100.0,
        "memory_limit_mb": 512.0,
    }
    base.update(overrides)
    return base


async def _create_system_aggregate(
    client: AsyncClient,
    db_session: AsyncSession,
    server_with_key: dict,
    period_type: PeriodType = PeriodType.hourly,
) -> None:
    """Вспомогательная функция: создаёт метрики и запускает агрегацию."""
    api_key = server_with_key["api_key"]
    server_id = server_with_key["id"]

    # Создаём сырые метрики
    for cpu in (10.0, 20.0, 30.0):
        await client.post(
            "/metrics",
            json={"cpu_percent": cpu, "memory_percent": 50.0, "disk_percent": 50.0},
            headers={"X-API-Key": api_key},
        )

    now = datetime.now(timezone.utc)
    period_start = now - timedelta(hours=2)
    period_end = now + timedelta(hours=1)

    await aggregate_system_metrics(
        db_session, server_id, period_type, period_start, period_end
    )


async def _create_docker_aggregate(
    client: AsyncClient,
    db_session: AsyncSession,
    server_with_key: dict,
    containers: list[str] | None = None,
) -> None:
    """Вспомогательная функция: создаёт docker-метрики и запускает агрегацию."""
    api_key = server_with_key["api_key"]
    server_id = server_with_key["id"]

    if containers is None:
        containers = ["pulsewatch_db"]

    # Создаём сырые docker-метрики
    for _ in range(3):
        payload = [
            _container_payload(name=name, container_id=f"id-{name}")
            for name in containers
        ]
        await client.post(
            "/docker-metrics", json=payload, headers={"X-API-Key": api_key}
        )

    now = datetime.now(timezone.utc)
    period_start = now - timedelta(hours=2)
    period_end = now + timedelta(hours=1)

    await aggregate_docker_metrics(
        db_session, server_id, PeriodType.hourly, period_start, period_end
    )


# ── Системные агрегаты ──────────────────────────────────────────────────────


async def test_get_system_aggregates_empty(
    client: AsyncClient,
    auth_headers: dict[str, str],
    server_with_key: dict,
):
    """GET агрегированных системных метрик — пустой список при отсутствии агрегатов."""
    server_id = server_with_key["id"]

    response = await client.get(
        f"/servers/{server_id}/metrics/aggregate",
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert response.json() == []


async def test_get_system_aggregates_with_data(
    client: AsyncClient,
    auth_headers: dict[str, str],
    server_with_key: dict,
    db_session: AsyncSession,
):
    """GET агрегированных системных метрик — данные есть после агрегации."""
    server_id = server_with_key["id"]

    await _create_system_aggregate(client, db_session, server_with_key)

    response = await client.get(
        f"/servers/{server_id}/metrics/aggregate",
        headers=auth_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    agg = body[0]
    assert agg["server_id"] == server_id
    assert agg["period_type"] == "hourly"
    assert agg["sample_count"] == 3
    assert abs(agg["avg_cpu"] - 20.0) < 0.01
    assert agg["min_cpu"] == 10.0
    assert agg["max_cpu"] == 30.0


async def test_get_system_aggregates_filter_daily(
    client: AsyncClient,
    auth_headers: dict[str, str],
    server_with_key: dict,
    db_session: AsyncSession,
):
    """GET агрегированных метрик с фильтром period=daily — пусто, т.к. агрегация hourly."""
    server_id = server_with_key["id"]

    await _create_system_aggregate(client, db_session, server_with_key, PeriodType.hourly)

    # Запрос с фильтром daily — должны получить пустой список
    response = await client.get(
        f"/servers/{server_id}/metrics/aggregate?period=daily",
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert response.json() == []

    # Запрос с фильтром hourly — должны получить данные
    response = await client.get(
        f"/servers/{server_id}/metrics/aggregate?period=hourly",
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert len(response.json()) == 1


async def test_get_system_aggregates_not_owner(
    client: AsyncClient,
    server_with_key: dict,
):
    """GET агрегированных метрик чужого сервера → 404."""
    server_id = server_with_key["id"]

    # Регистрируем другого пользователя (bob)
    await client.post(
        "/auth/register",
        json={"email": "bob@example.com", "password": "secret456"},
    )
    bob_token = (
        await client.post(
            "/auth/login",
            data={"username": "bob@example.com", "password": "secret456"},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    ).json()["access_token"]
    bob_headers = {"Authorization": f"Bearer {bob_token}"}

    # bob запрашивает агрегаты сервера alice
    response = await client.get(
        f"/servers/{server_id}/metrics/aggregate",
        headers=bob_headers,
    )
    assert response.status_code == 404


# ── Docker агрегаты ──────────────────────────────────────────────────────────


async def test_get_docker_aggregates_empty(
    client: AsyncClient,
    auth_headers: dict[str, str],
    server_with_key: dict,
):
    """GET агрегированных docker-метрик — пустой список при отсутствии агрегатов."""
    server_id = server_with_key["id"]

    response = await client.get(
        f"/servers/{server_id}/docker-metrics/aggregate",
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert response.json() == []


async def test_get_docker_aggregates_with_data(
    client: AsyncClient,
    auth_headers: dict[str, str],
    server_with_key: dict,
    db_session: AsyncSession,
):
    """GET агрегированных docker-метрик — данные есть после агрегации."""
    server_id = server_with_key["id"]

    await _create_docker_aggregate(client, db_session, server_with_key)

    response = await client.get(
        f"/servers/{server_id}/docker-metrics/aggregate",
        headers=auth_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    agg = body[0]
    assert agg["server_id"] == server_id
    assert agg["container_name"] == "pulsewatch_db"
    assert agg["period_type"] == "hourly"
    assert agg["sample_count"] == 3


async def test_get_docker_aggregates_filter_container(
    client: AsyncClient,
    auth_headers: dict[str, str],
    server_with_key: dict,
    db_session: AsyncSession,
):
    """GET агрегированных docker-метрик с фильтром по container_name."""
    server_id = server_with_key["id"]

    await _create_docker_aggregate(
        client, db_session, server_with_key, containers=["db", "redis"]
    )

    # Фильтр по container_name=db — только один агрегат
    response = await client.get(
        f"/servers/{server_id}/docker-metrics/aggregate?container_name=db",
        headers=auth_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["container_name"] == "db"

    # Без фильтра — оба агрегата
    response = await client.get(
        f"/servers/{server_id}/docker-metrics/aggregate",
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert len(response.json()) == 2
