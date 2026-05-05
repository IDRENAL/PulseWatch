"""Тесты API событий алертов."""

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


async def test_list_alert_events_empty(client: AsyncClient, auth_headers: dict[str, str]):
    response = await client.get("/alerts/events", headers=auth_headers)
    assert response.status_code == 200
    assert response.json() == []


async def test_list_alert_events_with_data(
    client: AsyncClient,
    auth_headers: dict[str, str],
    server_with_key: dict,
):
    server_id = server_with_key["id"]

    # Создаём правило через API
    rule_resp = await client.post(
        "/alerts/rules",
        json={
            "server_id": server_id,
            "name": "High CPU",
            "metric_type": "system",
            "metric_field": "cpu_percent",
            "operator": "gt",
            "threshold_value": 90.0,
        },
        headers=auth_headers,
    )
    assert rule_resp.status_code == 201
    rule_id = rule_resp.json()["id"]

    # Отправляем метрику, которая вызывает срабатывание правила (cpu=95 > 90)
    await client.post(
        "/metrics",
        json={"cpu_percent": 95.0, "memory_percent": 50.0, "disk_percent": 30.0},
        headers={"X-API-Key": server_with_key["api_key"]},
    )

    # Проверяем события
    response = await client.get("/alerts/events", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert len(body) >= 1
    event = body[0]
    assert event["rule_id"] == rule_id
    assert event["server_id"] == server_id
    assert event["metric_value"] == 95.0
    assert event["threshold_value"] == 90.0
    assert "cpu_percent" in event["message"]


async def test_list_alert_events_filter_by_server(
    client: AsyncClient,
    auth_headers: dict[str, str],
    server_with_key: dict,
):
    server_id = server_with_key["id"]

    # Создаём второй сервер
    server2 = (
        await client.post(
            "/servers/register",
            json={"name": "web-prod-02"},
            headers=auth_headers,
        )
    ).json()

    # Создаём правила для обоих серверов
    await client.post(
        "/alerts/rules",
        json={
            "server_id": server_id,
            "name": "High CPU S1",
            "metric_type": "system",
            "metric_field": "cpu_percent",
            "operator": "gt",
            "threshold_value": 90.0,
        },
        headers=auth_headers,
    )
    await client.post(
        "/alerts/rules",
        json={
            "server_id": server2["id"],
            "name": "High CPU S2",
            "metric_type": "system",
            "metric_field": "cpu_percent",
            "operator": "gt",
            "threshold_value": 90.0,
        },
        headers=auth_headers,
    )

    # Вызываем срабатывание обоих
    await client.post(
        "/metrics",
        json={"cpu_percent": 95.0, "memory_percent": 50.0, "disk_percent": 30.0},
        headers={"X-API-Key": server_with_key["api_key"]},
    )
    await client.post(
        "/metrics",
        json={"cpu_percent": 96.0, "memory_percent": 50.0, "disk_percent": 30.0},
        headers={"X-API-Key": server2["api_key"]},
    )

    # Фильтрация по server_id
    response = await client.get(f"/alerts/events?server_id={server_id}", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert len(body) >= 1
    assert all(e["server_id"] == server_id for e in body)


async def test_list_alert_events_filter_by_rule(
    client: AsyncClient,
    auth_headers: dict[str, str],
    server_with_key: dict,
):
    server_id = server_with_key["id"]

    # Создаём два правила
    rule1 = (
        await client.post(
            "/alerts/rules",
            json={
                "server_id": server_id,
                "name": "CPU Rule",
                "metric_type": "system",
                "metric_field": "cpu_percent",
                "operator": "gt",
                "threshold_value": 90.0,
            },
            headers=auth_headers,
        )
    ).json()

    await client.post(
        "/alerts/rules",
        json={
            "server_id": server_id,
            "name": "Memory Rule",
            "metric_type": "system",
            "metric_field": "memory_percent",
            "operator": "gt",
            "threshold_value": 80.0,
        },
        headers=auth_headers,
    )

    # Вызываем срабатывание обоих
    await client.post(
        "/metrics",
        json={"cpu_percent": 95.0, "memory_percent": 90.0, "disk_percent": 30.0},
        headers={"X-API-Key": server_with_key["api_key"]},
    )

    # Фильтрация по rule_id
    response = await client.get(f"/alerts/events?rule_id={rule1['id']}", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert len(body) >= 1
    assert all(e["rule_id"] == rule1["id"] for e in body)


async def test_get_alert_event(
    client: AsyncClient,
    auth_headers: dict[str, str],
    server_with_key: dict,
):
    server_id = server_with_key["id"]

    # Создаём правило и вызываем событие
    await client.post(
        "/alerts/rules",
        json={
            "server_id": server_id,
            "name": "High CPU",
            "metric_type": "system",
            "metric_field": "cpu_percent",
            "operator": "gt",
            "threshold_value": 90.0,
        },
        headers=auth_headers,
    )
    await client.post(
        "/metrics",
        json={"cpu_percent": 95.0, "memory_percent": 50.0, "disk_percent": 30.0},
        headers={"X-API-Key": server_with_key["api_key"]},
    )

    # Получаем список событий для нахождения event_id
    events = (await client.get("/alerts/events", headers=auth_headers)).json()
    assert len(events) >= 1
    event_id = events[0]["id"]

    # Получаем конкретное событие
    response = await client.get(f"/alerts/events/{event_id}", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["id"] == event_id
    assert response.json()["metric_value"] == 95.0


async def test_get_alert_event_not_found(client: AsyncClient, auth_headers: dict[str, str]):
    response = await client.get("/alerts/events/9999", headers=auth_headers)
    assert response.status_code == 404


async def test_alert_events_isolation(client: AsyncClient):
    """Пользователь не может видеть события алертов другого пользователя."""
    # Alice создаёт пользователя, сервер, правило, отправляет метрику
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

    await client.post(
        "/alerts/rules",
        json={
            "server_id": alice_server["id"],
            "name": "Alice CPU Rule",
            "metric_type": "system",
            "metric_field": "cpu_percent",
            "operator": "gt",
            "threshold_value": 90.0,
        },
        headers=alice_headers,
    )

    # Вызываем алерт
    await client.post(
        "/metrics",
        json={"cpu_percent": 95.0, "memory_percent": 50.0, "disk_percent": 30.0},
        headers={"X-API-Key": alice_server["api_key"]},
    )

    # Alice видит своё событие
    alice_events = (await client.get("/alerts/events", headers=alice_headers)).json()
    assert len(alice_events) >= 1

    # Bob регистрируется, не видит событий
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

    bob_events = (await client.get("/alerts/events", headers=bob_headers)).json()
    assert bob_events == []

    # Bob не может напрямую получить событие Alice
    alice_event_id = alice_events[0]["id"]
    response = await client.get(f"/alerts/events/{alice_event_id}", headers=bob_headers)
    assert response.status_code == 404
