"""Тесты сервиса агрегации метрик."""

from datetime import UTC, datetime, timedelta

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.metric_aggregate import PeriodType
from app.services.aggregation import (
    aggregate_all_servers,
    aggregate_docker_metrics,
    aggregate_system_metrics,
)


@pytest_asyncio.fixture
async def server_with_key(client: AsyncClient, auth_headers: dict[str, str]) -> dict:
    """Создаёт сервер и возвращает его данные с api_key."""
    response = await client.post(
        "/servers/register",
        json={"name": "web-prod-01"},
        headers=auth_headers,
    )
    assert response.status_code == 201
    return response.json()


@pytest_asyncio.fixture
async def second_server_with_key(client: AsyncClient, auth_headers: dict[str, str]) -> dict:
    """Создаёт второй сервер и возвращает его данные с api_key."""
    response = await client.post(
        "/servers/register",
        json={"name": "web-prod-02"},
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


async def test_aggregate_system_metrics_basic(
    client: AsyncClient,
    auth_headers: dict[str, str],
    server_with_key: dict,
    db_session: AsyncSession,
):
    """Агрегация системных метрик: создание агрегата с корректными avg/min/max."""
    api_key = server_with_key["api_key"]
    server_id = server_with_key["id"]

    # Создаём 3 сырые метрики через API
    payloads = [
        {"cpu_percent": 10.0, "memory_percent": 20.0, "disk_percent": 30.0},
        {"cpu_percent": 20.0, "memory_percent": 40.0, "disk_percent": 60.0},
        {"cpu_percent": 30.0, "memory_percent": 60.0, "disk_percent": 90.0},
    ]
    for p in payloads:
        r = await client.post("/metrics", json=p, headers={"X-API-Key": api_key})
        assert r.status_code == 201

    # Задаём период агрегации — широкий диапазон, включающий все метрики
    now = datetime.now(UTC)
    period_start = now - timedelta(hours=2)
    period_end = now + timedelta(hours=1)

    agg = await aggregate_system_metrics(
        db_session, server_id, PeriodType.hourly, period_start, period_end
    )

    assert agg is not None
    assert agg.server_id == server_id
    assert agg.period_type == PeriodType.hourly
    assert agg.sample_count == 3
    # avg_cpu = (10 + 20 + 30) / 3 = 20.0
    assert abs(agg.avg_cpu - 20.0) < 0.01
    assert agg.min_cpu == 10.0
    assert agg.max_cpu == 30.0
    # avg_memory = (20 + 40 + 60) / 3 = 40.0
    assert abs(agg.avg_memory - 40.0) < 0.01
    assert agg.min_memory == 20.0
    assert agg.max_memory == 60.0
    # avg_disk = (30 + 60 + 90) / 3 = 60.0
    assert abs(agg.avg_disk - 60.0) < 0.01
    assert agg.min_disk == 30.0
    assert agg.max_disk == 90.0


async def test_aggregate_system_metrics_no_data(
    client: AsyncClient,
    auth_headers: dict[str, str],
    server_with_key: dict,
    db_session: AsyncSession,
):
    """Агрегация для сервера без метрик возвращает None."""
    server_id = server_with_key["id"]
    now = datetime.now(UTC)
    period_start = now - timedelta(hours=1)
    period_end = now + timedelta(hours=1)

    result = await aggregate_system_metrics(
        db_session, server_id, PeriodType.hourly, period_start, period_end
    )

    assert result is None


async def test_aggregate_system_metrics_upsert(
    client: AsyncClient,
    auth_headers: dict[str, str],
    server_with_key: dict,
    db_session: AsyncSession,
):
    """Повторная агрегация за тот же период обновляет запись (UPSERT), не дублирует."""
    api_key = server_with_key["api_key"]
    server_id = server_with_key["id"]

    # Создаём 3 метрики через API (все до первой агрегации)
    for cpu in (10.0, 20.0, 30.0):
        await client.post(
            "/metrics",
            json={"cpu_percent": cpu, "memory_percent": 50.0, "disk_percent": 50.0},
            headers={"X-API-Key": api_key},
        )

    now = datetime.now(UTC)
    period_start = now - timedelta(hours=2)
    period_end = now + timedelta(hours=1)

    # Первая агрегация
    agg1 = await aggregate_system_metrics(
        db_session, server_id, PeriodType.hourly, period_start, period_end
    )
    assert agg1 is not None
    assert agg1.sample_count == 3
    assert abs(agg1.avg_cpu - 20.0) < 0.01

    # Вторая агрегация за тот же период — UPSERT (данные не изменились)
    agg2 = await aggregate_system_metrics(
        db_session, server_id, PeriodType.hourly, period_start, period_end
    )
    assert agg2 is not None
    assert agg2.id == agg1.id  # та же запись, не дубликат
    assert agg2.sample_count == 3
    assert abs(agg2.avg_cpu - 20.0) < 0.01

    # Проверяем, что в БД только одна запись агрегата
    from sqlalchemy import func, select

    from app.models.metric_aggregate import MetricAggregate

    count_result = await db_session.execute(
        select(func.count(MetricAggregate.id)).where(
            MetricAggregate.server_id == server_id,
            MetricAggregate.period_type == PeriodType.hourly,
            MetricAggregate.period_start == period_start,
        )
    )
    assert count_result.scalar() == 1


async def test_aggregate_docker_metrics_basic(
    client: AsyncClient,
    auth_headers: dict[str, str],
    server_with_key: dict,
    db_session: AsyncSession,
):
    """Агрегация docker-метрик: создание агрегата с корректными значениями."""
    api_key = server_with_key["api_key"]
    server_id = server_with_key["id"]

    # Создаём 3 snapshot'а docker-метрик для одного контейнера
    for cpu in (10.0, 20.0, 30.0):
        payload = [_container_payload(name="pulsewatch_db", cpu_percent=cpu)]
        r = await client.post("/docker-metrics", json=payload, headers={"X-API-Key": api_key})
        assert r.status_code == 201

    now = datetime.now(UTC)
    period_start = now - timedelta(hours=2)
    period_end = now + timedelta(hours=1)

    aggregates = await aggregate_docker_metrics(
        db_session, server_id, PeriodType.hourly, period_start, period_end
    )

    assert len(aggregates) == 1
    agg = aggregates[0]
    assert agg.container_name == "pulsewatch_db"
    assert agg.sample_count == 3
    assert abs(agg.avg_cpu - 20.0) < 0.01
    assert agg.min_cpu == 10.0
    assert agg.max_cpu == 30.0


async def test_aggregate_docker_metrics_multiple_containers(
    client: AsyncClient,
    auth_headers: dict[str, str],
    server_with_key: dict,
    db_session: AsyncSession,
):
    """Агрегация docker-метрик: два контейнера → два агрегата."""
    api_key = server_with_key["api_key"]
    server_id = server_with_key["id"]

    # Один батч с двумя контейнерами
    payload = [
        _container_payload(name="db", container_id="id-db", cpu_percent=10.0),
        _container_payload(name="redis", container_id="id-redis", cpu_percent=50.0),
    ]
    r = await client.post("/docker-metrics", json=payload, headers={"X-API-Key": api_key})
    assert r.status_code == 201

    now = datetime.now(UTC)
    period_start = now - timedelta(hours=2)
    period_end = now + timedelta(hours=1)

    aggregates = await aggregate_docker_metrics(
        db_session, server_id, PeriodType.hourly, period_start, period_end
    )

    assert len(aggregates) == 2
    container_names = {agg.container_name for agg in aggregates}
    assert container_names == {"db", "redis"}

    # Проверяем значения каждого агрегата
    agg_by_name = {agg.container_name: agg for agg in aggregates}
    assert agg_by_name["db"].avg_cpu == 10.0
    assert agg_by_name["db"].sample_count == 1
    assert agg_by_name["redis"].avg_cpu == 50.0
    assert agg_by_name["redis"].sample_count == 1


async def test_aggregate_docker_metrics_no_data(
    client: AsyncClient,
    auth_headers: dict[str, str],
    server_with_key: dict,
    db_session: AsyncSession,
):
    """Агрегация docker-метрик: нет данных → пустой список."""
    server_id = server_with_key["id"]
    now = datetime.now(UTC)
    period_start = now - timedelta(hours=1)
    period_end = now + timedelta(hours=1)

    result = await aggregate_docker_metrics(
        db_session, server_id, PeriodType.hourly, period_start, period_end
    )

    assert result == []


async def test_aggregate_all_servers(
    client: AsyncClient,
    auth_headers: dict[str, str],
    server_with_key: dict,
    second_server_with_key: dict,
    db_session: AsyncSession,
):
    """Агрегация всех серверов: оба сервера получают агрегаты."""
    # Создаём метрики для первого сервера
    await client.post(
        "/metrics",
        json={"cpu_percent": 10.0, "memory_percent": 20.0, "disk_percent": 30.0},
        headers={"X-API-Key": server_with_key["api_key"]},
    )
    # Создаём метрики для второго сервера
    await client.post(
        "/metrics",
        json={"cpu_percent": 50.0, "memory_percent": 60.0, "disk_percent": 70.0},
        headers={"X-API-Key": second_server_with_key["api_key"]},
    )

    now = datetime.now(UTC)
    period_start = now - timedelta(hours=2)
    period_end = now + timedelta(hours=1)

    await aggregate_all_servers(db_session, PeriodType.hourly, period_start, period_end)

    # Проверяем, что агрегаты созданы для обоих серверов
    from sqlalchemy import select

    from app.models.metric_aggregate import MetricAggregate

    result = await db_session.execute(select(MetricAggregate))
    all_aggregates = result.scalars().all()

    assert len(all_aggregates) == 2
    server_ids = {agg.server_id for agg in all_aggregates}
    assert server_ids == {server_with_key["id"], second_server_with_key["id"]}
