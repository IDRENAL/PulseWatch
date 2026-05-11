"""Smoke-тесты Prometheus-эндпоинта."""

from httpx import AsyncClient


async def test_prometheus_endpoint_returns_200(client: AsyncClient):
    response = await client.get("/metrics/prometheus")
    assert response.status_code == 200


async def test_prometheus_endpoint_returns_text_plain(client: AsyncClient):
    """Prometheus exposition format — text/plain; version=0.0.4."""
    response = await client.get("/metrics/prometheus")
    assert response.headers["content-type"].startswith("text/plain")


async def test_prometheus_endpoint_exposes_http_metrics(client: AsyncClient):
    """После реального запроса в дампе должен быть счётчик http_requests."""
    await client.get("/health")
    response = await client.get("/metrics/prometheus")
    body = response.text
    assert "http_requests_total" in body or "http_request_duration_seconds" in body


async def test_prometheus_endpoint_hidden_from_openapi(client: AsyncClient):
    """include_in_schema=False → /metrics/prometheus не должен быть в /openapi.json."""
    response = await client.get("/openapi.json")
    paths = response.json()["paths"]
    assert "/metrics/prometheus" not in paths
