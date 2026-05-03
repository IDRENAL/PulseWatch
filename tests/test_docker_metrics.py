import pytest_asyncio
from httpx import AsyncClient


def _container_payload(name: str = "pulsewatch_db", **overrides) -> dict:
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


@pytest_asyncio.fixture
async def server_with_key(
    client: AsyncClient, auth_headers: dict[str, str]
) -> dict:
    response = await client.post(
        "/servers/register",
        json={"name": "web-prod-01"},
        headers=auth_headers,
    )
    assert response.status_code == 201
    return response.json()


async def test_submit_docker_metrics_with_valid_key_returns_201(
    client: AsyncClient, server_with_key: dict
):
    payload = [_container_payload(name="pulsewatch_db")]
    response = await client.post(
        "/docker-metrics",
        json=payload,
        headers={"X-API-Key": server_with_key["api_key"]},
    )
    assert response.status_code == 201
    assert response.json() == {"status": "ok", "count": 1}


async def test_submit_docker_metrics_batch(
    client: AsyncClient, server_with_key: dict
):
    payload = [
        _container_payload(name="pulsewatch_db", container_id="aaa"),
        _container_payload(name="pulsewatch_redis", container_id="bbb"),
        _container_payload(
            name="nsam_db", container_id="ccc", status="exited",
            cpu_percent=0.0, memory_usage_mb=0.0, memory_limit_mb=None,
        ),
    ]
    response = await client.post(
        "/docker-metrics",
        json=payload,
        headers={"X-API-Key": server_with_key["api_key"]},
    )
    assert response.status_code == 201
    assert response.json() == {"status": "ok", "count": 3}


async def test_submit_docker_metrics_empty_list_accepted(
    client: AsyncClient, server_with_key: dict
):
    response = await client.post(
        "/docker-metrics",
        json=[],
        headers={"X-API-Key": server_with_key["api_key"]},
    )
    assert response.status_code == 201
    assert response.json() == {"status": "ok", "count": 0}


async def test_submit_docker_metrics_without_key_returns_401(client: AsyncClient):
    response = await client.post("/docker-metrics", json=[_container_payload()])
    assert response.status_code == 401


async def test_submit_docker_metrics_with_malformed_key_returns_401(
    client: AsyncClient,
):
    response = await client.post(
        "/docker-metrics",
        json=[_container_payload()],
        headers={"X-API-Key": "not-a-valid-key"},
    )
    assert response.status_code == 401


async def test_submit_docker_metrics_with_wrong_secret_returns_401(
    client: AsyncClient, server_with_key: dict
):
    server_id = server_with_key["id"]
    response = await client.post(
        "/docker-metrics",
        json=[_container_payload()],
        headers={"X-API-Key": f"{server_id}.totally-wrong-secret"},
    )
    assert response.status_code == 401


async def test_submit_docker_metrics_missing_field_returns_422(
    client: AsyncClient, server_with_key: dict
):
    bad = _container_payload()
    del bad["image"]
    response = await client.post(
        "/docker-metrics",
        json=[bad],
        headers={"X-API-Key": server_with_key["api_key"]},
    )
    assert response.status_code == 422


async def test_submit_docker_metrics_memory_limit_optional(
    client: AsyncClient, server_with_key: dict
):
    # memory_limit_mb отсутствует в payload — должно прийти как None.
    payload_item = _container_payload()
    del payload_item["memory_limit_mb"]
    response = await client.post(
        "/docker-metrics",
        json=[payload_item],
        headers={"X-API-Key": server_with_key["api_key"]},
    )
    assert response.status_code == 201


async def test_submit_docker_metrics_updates_last_seen_at(
    client: AsyncClient,
    auth_headers: dict[str, str],
    server_with_key: dict,
):
    server_id = server_with_key["id"]
    assert server_with_key["last_seen_at"] is None

    response = await client.post(
        "/docker-metrics",
        json=[],
        headers={"X-API-Key": server_with_key["api_key"]},
    )
    assert response.status_code == 201

    servers = (await client.get("/servers/me", headers=auth_headers)).json()
    found = next(s for s in servers if s["id"] == server_id)
    assert found["last_seen_at"] is not None


async def test_get_docker_metrics_returns_in_descending_order(
    client: AsyncClient,
    auth_headers: dict[str, str],
    server_with_key: dict,
):
    api_key = server_with_key["api_key"]
    server_id = server_with_key["id"]

    # Три батча с разными CPU — каждый батч это отдельный snapshot во времени.
    for cpu in (10.0, 11.0, 12.0):
        await client.post(
            "/docker-metrics",
            json=[_container_payload(cpu_percent=cpu)],
            headers={"X-API-Key": api_key},
        )

    response = await client.get(
        f"/servers/{server_id}/docker-metrics", headers=auth_headers
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 3
    cpus = [m["cpu_percent"] for m in body]
    assert cpus == sorted(cpus, reverse=True)
    assert all(m["server_id"] == server_id for m in body)


async def test_get_docker_metrics_respects_limit(
    client: AsyncClient,
    auth_headers: dict[str, str],
    server_with_key: dict,
):
    api_key = server_with_key["api_key"]
    server_id = server_with_key["id"]

    # Один батч с 5 контейнерами = 5 строк в БД.
    payload = [
        _container_payload(name=f"c{i}", container_id=f"id{i}") for i in range(5)
    ]
    await client.post(
        "/docker-metrics", json=payload, headers={"X-API-Key": api_key}
    )

    response = await client.get(
        f"/servers/{server_id}/docker-metrics?limit=2", headers=auth_headers
    )
    assert response.status_code == 200
    assert len(response.json()) == 2


async def test_get_docker_metrics_filter_by_container_id(
    client: AsyncClient,
    auth_headers: dict[str, str],
    server_with_key: dict,
):
    api_key = server_with_key["api_key"]
    server_id = server_with_key["id"]

    payload = [
        _container_payload(name="db", container_id="db-id"),
        _container_payload(name="redis", container_id="redis-id"),
        _container_payload(name="app", container_id="app-id"),
    ]
    await client.post(
        "/docker-metrics", json=payload, headers={"X-API-Key": api_key}
    )

    response = await client.get(
        f"/servers/{server_id}/docker-metrics?container_id=redis-id",
        headers=auth_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["container_id"] == "redis-id"


async def test_get_docker_metrics_limit_validation(
    client: AsyncClient,
    auth_headers: dict[str, str],
    server_with_key: dict,
):
    server_id = server_with_key["id"]
    response = await client.get(
        f"/servers/{server_id}/docker-metrics?limit=0", headers=auth_headers
    )
    assert response.status_code == 422

    response = await client.get(
        f"/servers/{server_id}/docker-metrics?limit=10000", headers=auth_headers
    )
    assert response.status_code == 422


async def test_get_docker_metrics_unknown_server_returns_404(
    client: AsyncClient, auth_headers: dict[str, str]
):
    response = await client.get(
        "/servers/9999/docker-metrics", headers=auth_headers
    )
    assert response.status_code == 404


async def test_get_docker_metrics_foreign_server_returns_404(client: AsyncClient):
    # alice
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
    alice_server = (
        await client.post(
            "/servers/register",
            json={"name": "alice-server"},
            headers={"Authorization": f"Bearer {alice_token}"},
        )
    ).json()

    # bob пытается посмотреть docker-метрики сервера alice
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

    response = await client.get(
        f"/servers/{alice_server['id']}/docker-metrics",
        headers={"Authorization": f"Bearer {bob_token}"},
    )
    assert response.status_code == 404


async def test_get_docker_metrics_without_auth_returns_401(client: AsyncClient):
    response = await client.get("/servers/1/docker-metrics")
    assert response.status_code == 401
