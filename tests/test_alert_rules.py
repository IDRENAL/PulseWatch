"""Тесты CRUD API правил алертов."""

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


def _rule_payload(server_id: int, **overrides) -> dict:
    base = {
        "server_id": server_id,
        "name": "High CPU",
        "metric_type": "system",
        "metric_field": "cpu_percent",
        "operator": "gt",
        "threshold_value": 90.0,
        "cooldown_seconds": 300,
        "is_active": True,
    }
    base.update(overrides)
    return base


# ─── CREATE ───────────────────────────────────────────────────────────────


async def test_create_alert_rule_system(
    client: AsyncClient, auth_headers: dict[str, str], server_with_key: dict
):
    payload = _rule_payload(server_with_key["id"])
    response = await client.post("/alerts/rules", json=payload, headers=auth_headers)
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "High CPU"
    assert body["metric_type"] == "system"
    assert body["metric_field"] == "cpu_percent"
    assert body["operator"] == "gt"
    assert body["threshold_value"] == 90.0
    assert body["server_id"] == server_with_key["id"]
    assert body["is_active"] is True
    assert body["cooldown_seconds"] == 300
    assert body["last_triggered_at"] is None
    assert "id" in body
    assert "created_at" in body


async def test_create_alert_rule_docker(
    client: AsyncClient, auth_headers: dict[str, str], server_with_key: dict
):
    payload = _rule_payload(
        server_with_key["id"],
        name="Docker CPU high",
        metric_type="docker",
        metric_field="cpu_percent",
        container_name="my_app",
        threshold_value=80.0,
    )
    response = await client.post("/alerts/rules", json=payload, headers=auth_headers)
    assert response.status_code == 201
    body = response.json()
    assert body["metric_type"] == "docker"
    assert body["container_name"] == "my_app"
    assert body["threshold_value"] == 80.0


async def test_create_alert_rule_server_not_found(
    client: AsyncClient, auth_headers: dict[str, str]
):
    payload = _rule_payload(9999)
    response = await client.post("/alerts/rules", json=payload, headers=auth_headers)
    assert response.status_code == 404


async def test_create_alert_rule_unauthenticated(client: AsyncClient, server_with_key: dict):
    payload = _rule_payload(server_with_key["id"])
    response = await client.post("/alerts/rules", json=payload)
    assert response.status_code == 401


# ─── LIST ─────────────────────────────────────────────────────────────────


async def test_list_alert_rules(
    client: AsyncClient, auth_headers: dict[str, str], server_with_key: dict
):
    server_id = server_with_key["id"]
    await client.post(
        "/alerts/rules",
        json=_rule_payload(server_id, name="Rule 1"),
        headers=auth_headers,
    )
    await client.post(
        "/alerts/rules",
        json=_rule_payload(server_id, name="Rule 2", metric_field="memory_percent"),
        headers=auth_headers,
    )

    response = await client.get("/alerts/rules", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
    names = {r["name"] for r in body}
    assert names == {"Rule 1", "Rule 2"}


async def test_list_alert_rules_filter_by_server(
    client: AsyncClient, auth_headers: dict[str, str], server_with_key: dict
):
    server_id = server_with_key["id"]

    # Создание второго сервера
    server2 = (
        await client.post(
            "/servers/register",
            json={"name": "web-prod-02"},
            headers=auth_headers,
        )
    ).json()

    await client.post(
        "/alerts/rules",
        json=_rule_payload(server_id, name="Rule for server 1"),
        headers=auth_headers,
    )
    await client.post(
        "/alerts/rules",
        json=_rule_payload(server2["id"], name="Rule for server 2"),
        headers=auth_headers,
    )

    response = await client.get(f"/alerts/rules?server_id={server_id}", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["name"] == "Rule for server 1"


# ─── GET ──────────────────────────────────────────────────────────────────


async def test_get_alert_rule(
    client: AsyncClient, auth_headers: dict[str, str], server_with_key: dict
):
    create_resp = await client.post(
        "/alerts/rules",
        json=_rule_payload(server_with_key["id"]),
        headers=auth_headers,
    )
    rule_id = create_resp.json()["id"]

    response = await client.get(f"/alerts/rules/{rule_id}", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["id"] == rule_id
    assert response.json()["name"] == "High CPU"


async def test_get_alert_rule_not_found(client: AsyncClient, auth_headers: dict[str, str]):
    response = await client.get("/alerts/rules/9999", headers=auth_headers)
    assert response.status_code == 404


# ─── UPDATE ───────────────────────────────────────────────────────────────


async def test_update_alert_rule(
    client: AsyncClient, auth_headers: dict[str, str], server_with_key: dict
):
    create_resp = await client.post(
        "/alerts/rules",
        json=_rule_payload(server_with_key["id"]),
        headers=auth_headers,
    )
    rule_id = create_resp.json()["id"]

    response = await client.patch(
        f"/alerts/rules/{rule_id}",
        json={"name": "Updated CPU Rule", "threshold_value": 95.0, "is_active": False},
        headers=auth_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Updated CPU Rule"
    assert body["threshold_value"] == 95.0
    assert body["is_active"] is False


async def test_update_alert_rule_partial(
    client: AsyncClient, auth_headers: dict[str, str], server_with_key: dict
):
    create_resp = await client.post(
        "/alerts/rules",
        json=_rule_payload(server_with_key["id"]),
        headers=auth_headers,
    )
    rule_id = create_resp.json()["id"]
    original_threshold = create_resp.json()["threshold_value"]

    response = await client.patch(
        f"/alerts/rules/{rule_id}",
        json={"name": "Only name changed"},
        headers=auth_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Only name changed"
    assert body["threshold_value"] == original_threshold


# ─── DELETE ───────────────────────────────────────────────────────────────


async def test_delete_alert_rule(
    client: AsyncClient, auth_headers: dict[str, str], server_with_key: dict
):
    create_resp = await client.post(
        "/alerts/rules",
        json=_rule_payload(server_with_key["id"]),
        headers=auth_headers,
    )
    rule_id = create_resp.json()["id"]

    response = await client.delete(f"/alerts/rules/{rule_id}", headers=auth_headers)
    assert response.status_code == 204

    # Проверяем, что правило удалено
    get_resp = await client.get(f"/alerts/rules/{rule_id}", headers=auth_headers)
    assert get_resp.status_code == 404


async def test_delete_alert_rule_not_found(client: AsyncClient, auth_headers: dict[str, str]):
    response = await client.delete("/alerts/rules/9999", headers=auth_headers)
    assert response.status_code == 404
