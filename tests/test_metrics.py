import pytest_asyncio
from httpx import AsyncClient


@pytest_asyncio.fixture
async def server_with_key(client: AsyncClient, auth_headers: dict[str, str]) -> dict:
    response = await client.post(
        "/servers/register",
        json={"name": "web-prod-01"},
        headers=auth_headers,
    )
    assert response.status_code == 201
    return response.json()


async def test_submit_metric_with_valid_key_returns_201(client: AsyncClient, server_with_key: dict):
    response = await client.post(
        "/metrics",
        json={"cpu_percent": 12.5, "memory_percent": 47.0, "disk_percent": 30.1},
        headers={"X-API-Key": server_with_key["api_key"]},
    )
    assert response.status_code == 201
    assert response.json() == {"status": "ok"}


async def test_submit_metric_without_key_returns_401(client: AsyncClient):
    response = await client.post(
        "/metrics",
        json={"cpu_percent": 1.0, "memory_percent": 1.0, "disk_percent": 1.0},
    )
    assert response.status_code == 401


async def test_submit_metric_with_malformed_key_returns_401(client: AsyncClient):
    response = await client.post(
        "/metrics",
        json={"cpu_percent": 1.0, "memory_percent": 1.0, "disk_percent": 1.0},
        headers={"X-API-Key": "not-a-valid-key"},
    )
    assert response.status_code == 401


async def test_submit_metric_with_wrong_secret_returns_401(
    client: AsyncClient, server_with_key: dict
):
    server_id = server_with_key["id"]
    response = await client.post(
        "/metrics",
        json={"cpu_percent": 1.0, "memory_percent": 1.0, "disk_percent": 1.0},
        headers={"X-API-Key": f"{server_id}.totally-wrong-secret"},
    )
    assert response.status_code == 401


async def test_submit_metric_for_unknown_server_returns_401(client: AsyncClient):
    response = await client.post(
        "/metrics",
        json={"cpu_percent": 1.0, "memory_percent": 1.0, "disk_percent": 1.0},
        headers={"X-API-Key": "9999.some-secret"},
    )
    assert response.status_code == 401


async def test_get_metrics_returns_in_descending_order(
    client: AsyncClient,
    auth_headers: dict[str, str],
    server_with_key: dict,
):
    api_key = server_with_key["api_key"]
    server_id = server_with_key["id"]

    payloads = [
        {"cpu_percent": 10.0, "memory_percent": 20.0, "disk_percent": 30.0},
        {"cpu_percent": 11.0, "memory_percent": 21.0, "disk_percent": 31.0},
        {"cpu_percent": 12.0, "memory_percent": 22.0, "disk_percent": 32.0},
    ]
    for p in payloads:
        r = await client.post("/metrics", json=p, headers={"X-API-Key": api_key})
        assert r.status_code == 201

    response = await client.get(f"/servers/{server_id}/metrics", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 3

    cpus = [m["cpu_percent"] for m in body]
    assert cpus == sorted(cpus, reverse=True)
    assert all(m["server_id"] == server_id for m in body)


async def test_get_metrics_respects_limit(
    client: AsyncClient,
    auth_headers: dict[str, str],
    server_with_key: dict,
):
    api_key = server_with_key["api_key"]
    server_id = server_with_key["id"]

    for i in range(5):
        await client.post(
            "/metrics",
            json={
                "cpu_percent": float(i),
                "memory_percent": 0.0,
                "disk_percent": 0.0,
            },
            headers={"X-API-Key": api_key},
        )

    response = await client.get(f"/servers/{server_id}/metrics?limit=2", headers=auth_headers)
    assert response.status_code == 200
    assert len(response.json()) == 2


async def test_get_metrics_limit_validation(
    client: AsyncClient,
    auth_headers: dict[str, str],
    server_with_key: dict,
):
    server_id = server_with_key["id"]
    response = await client.get(f"/servers/{server_id}/metrics?limit=0", headers=auth_headers)
    assert response.status_code == 422

    response = await client.get(f"/servers/{server_id}/metrics?limit=10000", headers=auth_headers)
    assert response.status_code == 422


async def test_get_metrics_unknown_server_returns_404(
    client: AsyncClient, auth_headers: dict[str, str]
):
    response = await client.get("/servers/9999/metrics", headers=auth_headers)
    assert response.status_code == 404


async def test_get_metrics_foreign_server_returns_404(client: AsyncClient):
    # alice создаёт сервер.
    await client.post(
        "/auth/register",
        json={"email": "alice@example.com", "password": "secret123"},
    )
    alice_token = (
        await client.post(
            "/auth/login",
            data={"username": "alice@example.com", "password": "secret123"},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    ).json()["access_token"]
    alice_headers = {"Authorization": f"Bearer {alice_token}"}

    alice_server = (
        await client.post(
            "/servers/register",
            json={"name": "alice-server"},
            headers=alice_headers,
        )
    ).json()

    # bob пробует посмотреть метрики сервера alice.
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

    response = await client.get(f"/servers/{alice_server['id']}/metrics", headers=bob_headers)
    # 404, не 403 — защита от энумерации id.
    assert response.status_code == 404


async def test_get_metrics_without_auth_returns_401(client: AsyncClient):
    response = await client.get("/servers/1/metrics")
    assert response.status_code == 401


async def test_submit_metric_updates_last_seen_at(
    client: AsyncClient,
    auth_headers: dict[str, str],
    server_with_key: dict,
):
    server_id = server_with_key["id"]
    assert server_with_key["last_seen_at"] is None

    r = await client.post(
        "/metrics",
        json={"cpu_percent": 5.0, "memory_percent": 5.0, "disk_percent": 5.0},
        headers={"X-API-Key": server_with_key["api_key"]},
    )
    assert r.status_code == 201

    servers = (await client.get("/servers/me", headers=auth_headers)).json()
    found = next(s for s in servers if s["id"] == server_id)
    assert found["last_seen_at"] is not None


async def test_submit_metric_records_agent_version(
    client: AsyncClient,
    auth_headers: dict[str, str],
    server_with_key: dict,
):
    """POST /metrics с agent_version → ServerRead.agent_version обновляется."""
    server_id = server_with_key["id"]
    api_key = server_with_key["api_key"]

    # сразу после регистрации — версия неизвестна
    assert server_with_key.get("agent_version") is None

    await client.post(
        "/metrics",
        json={
            "cpu_percent": 5.0,
            "memory_percent": 5.0,
            "disk_percent": 5.0,
            "agent_version": "1.2.3",
        },
        headers={"X-API-Key": api_key},
    )

    servers = (await client.get("/servers/me", headers=auth_headers)).json()
    found = next(s for s in servers if s["id"] == server_id)
    assert found["agent_version"] == "1.2.3"


async def test_submit_metric_without_agent_version_keeps_existing(
    client: AsyncClient,
    auth_headers: dict[str, str],
    server_with_key: dict,
):
    """Метрика без agent_version не затирает уже сохранённую версию."""
    server_id = server_with_key["id"]
    api_key = server_with_key["api_key"]

    # Первый раз: версия 1.0.0
    await client.post(
        "/metrics",
        json={
            "cpu_percent": 1.0,
            "memory_percent": 1.0,
            "disk_percent": 1.0,
            "agent_version": "1.0.0",
        },
        headers={"X-API-Key": api_key},
    )

    # Второй раз: без поля
    await client.post(
        "/metrics",
        json={"cpu_percent": 2.0, "memory_percent": 2.0, "disk_percent": 2.0},
        headers={"X-API-Key": api_key},
    )

    servers = (await client.get("/servers/me", headers=auth_headers)).json()
    found = next(s for s in servers if s["id"] == server_id)
    assert found["agent_version"] == "1.0.0"


async def test_submit_metric_updates_agent_version_when_changed(
    client: AsyncClient,
    auth_headers: dict[str, str],
    server_with_key: dict,
):
    """При смене версии (например, после обновления агента) поле обновляется."""
    server_id = server_with_key["id"]
    api_key = server_with_key["api_key"]

    for version in ("1.0.0", "1.0.1", "2.0.0"):
        await client.post(
            "/metrics",
            json={
                "cpu_percent": 1.0,
                "memory_percent": 1.0,
                "disk_percent": 1.0,
                "agent_version": version,
            },
            headers={"X-API-Key": api_key},
        )

    servers = (await client.get("/servers/me", headers=auth_headers)).json()
    found = next(s for s in servers if s["id"] == server_id)
    assert found["agent_version"] == "2.0.0"
