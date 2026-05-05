"""Тесты CSV-экспорта метрик."""

import csv
import io
from datetime import UTC, datetime, timedelta

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.docker_aggregate import DockerAggregate
from app.models.metric_aggregate import MetricAggregate, PeriodType


@pytest_asyncio.fixture
async def server_with_key(client: AsyncClient, auth_headers: dict[str, str]) -> dict:
    response = await client.post(
        "/servers/register",
        json={"name": "web-prod-01"},
        headers=auth_headers,
    )
    assert response.status_code == 201
    return response.json()


def _parse_csv(text: str) -> tuple[list[str], list[dict]]:
    """Разбирает CSV-текст: возвращает (header, list_of_rows)."""
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    return rows[0], [dict(zip(rows[0], row, strict=True)) for row in rows[1:]]


# ─── System raw ────────────────────────────────────────────────────────────


async def test_export_system_raw_returns_csv(
    client: AsyncClient,
    auth_headers: dict[str, str],
    server_with_key: dict,
):
    api_key = server_with_key["api_key"]
    server_id = server_with_key["id"]

    for i in range(3):
        r = await client.post(
            "/metrics",
            json={
                "cpu_percent": float(10 + i),
                "memory_percent": float(20 + i),
                "disk_percent": float(30 + i),
            },
            headers={"X-API-Key": api_key},
        )
        assert r.status_code == 201

    now = datetime.now(UTC)
    response = await client.get(
        f"/servers/{server_id}/metrics/export",
        params={
            "start": (now - timedelta(hours=1)).isoformat(),
            "end": (now + timedelta(hours=1)).isoformat(),
            "granularity": "raw",
        },
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"]

    header, rows = _parse_csv(response.text)
    assert header == ["collected_at", "cpu_percent", "memory_percent", "disk_percent"]
    assert len(rows) == 3
    cpus = sorted(float(r["cpu_percent"]) for r in rows)
    assert cpus == [10.0, 11.0, 12.0]


async def test_export_system_raw_empty_range(
    client: AsyncClient,
    auth_headers: dict[str, str],
    server_with_key: dict,
):
    server_id = server_with_key["id"]
    now = datetime.now(UTC)
    response = await client.get(
        f"/servers/{server_id}/metrics/export",
        params={
            "start": (now - timedelta(hours=2)).isoformat(),
            "end": (now - timedelta(hours=1)).isoformat(),
            "granularity": "raw",
        },
        headers=auth_headers,
    )

    assert response.status_code == 200
    header, rows = _parse_csv(response.text)
    assert header == ["collected_at", "cpu_percent", "memory_percent", "disk_percent"]
    assert rows == []


# ─── System aggregated ─────────────────────────────────────────────────────


async def test_export_system_hourly_returns_csv(
    client: AsyncClient,
    auth_headers: dict[str, str],
    server_with_key: dict,
    db_session: AsyncSession,
):
    server_id = server_with_key["id"]

    period_start = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
    db_session.add(
        MetricAggregate(
            server_id=server_id,
            period_type=PeriodType.hourly,
            period_start=period_start,
            period_end=period_start + timedelta(hours=1),
            avg_cpu=50.0,
            min_cpu=40.0,
            max_cpu=60.0,
            avg_memory=70.0,
            min_memory=65.0,
            max_memory=75.0,
            avg_disk=80.0,
            min_disk=78.0,
            max_disk=82.0,
            sample_count=360,
        )
    )
    await db_session.commit()

    response = await client.get(
        f"/servers/{server_id}/metrics/export",
        params={
            "start": "2026-05-01T00:00:00+00:00",
            "end": "2026-05-02T00:00:00+00:00",
            "granularity": "hourly",
        },
        headers=auth_headers,
    )

    assert response.status_code == 200
    header, rows = _parse_csv(response.text)
    assert "avg_cpu" in header
    assert "sample_count" in header
    assert len(rows) == 1
    assert float(rows[0]["avg_cpu"]) == 50.0
    assert int(rows[0]["sample_count"]) == 360


# ─── Validation ────────────────────────────────────────────────────────────


async def test_export_range_too_large_returns_400(
    client: AsyncClient,
    auth_headers: dict[str, str],
    server_with_key: dict,
):
    """raw granularity ограничено 24 часами."""
    server_id = server_with_key["id"]
    now = datetime.now(UTC)
    response = await client.get(
        f"/servers/{server_id}/metrics/export",
        params={
            "start": (now - timedelta(days=2)).isoformat(),
            "end": now.isoformat(),
            "granularity": "raw",
        },
        headers=auth_headers,
    )
    assert response.status_code == 400


async def test_export_end_before_start_returns_400(
    client: AsyncClient,
    auth_headers: dict[str, str],
    server_with_key: dict,
):
    server_id = server_with_key["id"]
    now = datetime.now(UTC)
    response = await client.get(
        f"/servers/{server_id}/metrics/export",
        params={
            "start": now.isoformat(),
            "end": (now - timedelta(hours=1)).isoformat(),
            "granularity": "raw",
        },
        headers=auth_headers,
    )
    assert response.status_code == 400


async def test_export_invalid_granularity_returns_422(
    client: AsyncClient,
    auth_headers: dict[str, str],
    server_with_key: dict,
):
    server_id = server_with_key["id"]
    now = datetime.now(UTC)
    response = await client.get(
        f"/servers/{server_id}/metrics/export",
        params={
            "start": (now - timedelta(hours=1)).isoformat(),
            "end": now.isoformat(),
            "granularity": "weekly",
        },
        headers=auth_headers,
    )
    assert response.status_code == 422


async def test_export_unknown_server_returns_404(client: AsyncClient, auth_headers: dict[str, str]):
    now = datetime.now(UTC)
    response = await client.get(
        "/servers/9999/metrics/export",
        params={
            "start": (now - timedelta(hours=1)).isoformat(),
            "end": now.isoformat(),
            "granularity": "raw",
        },
        headers=auth_headers,
    )
    assert response.status_code == 404


async def test_export_without_auth_returns_401(client: AsyncClient):
    now = datetime.now(UTC)
    response = await client.get(
        "/servers/1/metrics/export",
        params={
            "start": (now - timedelta(hours=1)).isoformat(),
            "end": now.isoformat(),
            "granularity": "raw",
        },
    )
    assert response.status_code == 401


# ─── Docker export ─────────────────────────────────────────────────────────


async def test_export_docker_raw_returns_csv(
    client: AsyncClient,
    auth_headers: dict[str, str],
    server_with_key: dict,
):
    api_key = server_with_key["api_key"]
    server_id = server_with_key["id"]

    payload = [
        {
            "container_id": "abc123",
            "container_name": "web",
            "image": "nginx:latest",
            "status": "running",
            "cpu_percent": 5.0,
            "memory_usage_mb": 128.0,
            "memory_limit_mb": 1024.0,
        },
        {
            "container_id": "def456",
            "container_name": "db",
            "image": "postgres:16",
            "status": "running",
            "cpu_percent": 15.0,
            "memory_usage_mb": 512.0,
            "memory_limit_mb": 2048.0,
        },
    ]
    r = await client.post("/docker-metrics", json=payload, headers={"X-API-Key": api_key})
    assert r.status_code == 201

    now = datetime.now(UTC)
    response = await client.get(
        f"/servers/{server_id}/docker-metrics/export",
        params={
            "start": (now - timedelta(hours=1)).isoformat(),
            "end": (now + timedelta(hours=1)).isoformat(),
            "granularity": "raw",
        },
        headers=auth_headers,
    )

    assert response.status_code == 200
    header, rows = _parse_csv(response.text)
    assert header[0] == "collected_at"
    assert "container_name" in header
    assert len(rows) == 2
    names = {r["container_name"] for r in rows}
    assert names == {"web", "db"}


async def test_export_docker_filter_by_container(
    client: AsyncClient,
    auth_headers: dict[str, str],
    server_with_key: dict,
):
    api_key = server_with_key["api_key"]
    server_id = server_with_key["id"]

    payload = [
        {
            "container_id": "abc",
            "container_name": "web",
            "image": "nginx",
            "status": "running",
            "cpu_percent": 1.0,
            "memory_usage_mb": 1.0,
            "memory_limit_mb": 100.0,
        },
        {
            "container_id": "def",
            "container_name": "db",
            "image": "postgres",
            "status": "running",
            "cpu_percent": 2.0,
            "memory_usage_mb": 2.0,
            "memory_limit_mb": 200.0,
        },
    ]
    await client.post("/docker-metrics", json=payload, headers={"X-API-Key": api_key})

    now = datetime.now(UTC)
    response = await client.get(
        f"/servers/{server_id}/docker-metrics/export",
        params={
            "start": (now - timedelta(hours=1)).isoformat(),
            "end": (now + timedelta(hours=1)).isoformat(),
            "granularity": "raw",
            "container_name": "web",
        },
        headers=auth_headers,
    )

    assert response.status_code == 200
    _, rows = _parse_csv(response.text)
    assert len(rows) == 1
    assert rows[0]["container_name"] == "web"


async def test_export_docker_hourly_returns_csv(
    client: AsyncClient,
    auth_headers: dict[str, str],
    server_with_key: dict,
    db_session: AsyncSession,
):
    server_id = server_with_key["id"]

    period_start = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
    db_session.add(
        DockerAggregate(
            server_id=server_id,
            container_name="web",
            period_type=PeriodType.hourly,
            period_start=period_start,
            period_end=period_start + timedelta(hours=1),
            avg_cpu=10.0,
            min_cpu=5.0,
            max_cpu=20.0,
            avg_memory_usage=200.0,
            max_memory_usage=300.0,
            total_rx_bytes=1024,
            total_tx_bytes=2048,
            sample_count=120,
        )
    )
    await db_session.commit()

    response = await client.get(
        f"/servers/{server_id}/docker-metrics/export",
        params={
            "start": "2026-05-01T00:00:00+00:00",
            "end": "2026-05-02T00:00:00+00:00",
            "granularity": "hourly",
        },
        headers=auth_headers,
    )

    assert response.status_code == 200
    header, rows = _parse_csv(response.text)
    assert "avg_cpu" in header
    assert "total_rx_bytes" in header
    assert len(rows) == 1
    assert rows[0]["container_name"] == "web"
    assert int(rows[0]["sample_count"]) == 120
