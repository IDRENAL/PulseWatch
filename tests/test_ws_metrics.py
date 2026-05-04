"""Тесты для Этапа 4: WebSocket real-time метрик через Redis Pub/Sub + Dashboard."""

import json
import time

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect


def _register_user(client: TestClient, email: str, password: str) -> str:
    """Регистрирует юзера и возвращает JWT."""
    client.post("/auth/register", json={"email": email, "password": password})
    response = client.post(
        "/auth/login",
        data={"username": email, "password": password},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    return response.json()["access_token"]


def _register_server(client: TestClient, token: str, name: str) -> dict:
    response = client.post(
        "/servers/register",
        json={"name": name},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 201
    return response.json()


# ─── WebSocket /ws/metrics/{server_id} — авторизация ────────────────────


def test_ws_metrics_without_token_closes_1008(sync_client: TestClient):
    with pytest.raises(WebSocketDisconnect) as exc:
        with sync_client.websocket_connect("/ws/metrics/1"):
            pass
    assert exc.value.code == 1008


def test_ws_metrics_with_invalid_token_closes_1008(sync_client: TestClient):
    with pytest.raises(WebSocketDisconnect) as exc:
        with sync_client.websocket_connect("/ws/metrics/1?token=garbage"):
            pass
    assert exc.value.code == 1008


def test_ws_metrics_with_unknown_server_closes_1008(sync_client: TestClient):
    token = _register_user(sync_client, "alice@example.com", "secret123")
    with pytest.raises(WebSocketDisconnect) as exc:
        with sync_client.websocket_connect(f"/ws/metrics/9999?token={token}"):
            pass
    assert exc.value.code == 1008


def test_ws_metrics_with_foreign_server_closes_1008(sync_client: TestClient):
    alice_token = _register_user(sync_client, "alice@example.com", "secret123")
    alice_server = _register_server(sync_client, alice_token, "alice-server")

    bob_token = _register_user(sync_client, "bob@example.com", "secret456")

    with pytest.raises(WebSocketDisconnect) as exc:
        with sync_client.websocket_connect(
            f"/ws/metrics/{alice_server['id']}?token={bob_token}"
        ):
            pass
    assert exc.value.code == 1008


def test_ws_metrics_valid_connection_accepted(sync_client: TestClient):
    """Успешное WS-подключение не закрывается мгновенно."""
    token = _register_user(sync_client, "alice@example.com", "secret123")
    server = _register_server(sync_client, token, "srv-01")

    with sync_client.websocket_connect(
        f"/ws/metrics/{server['id']}?token={token}"
    ) as ws:
        # Если подключение установлено — можно отправить ping-сообщение
        ws.send_text("ping")
        # WS остаётся открытым, никаких исключений


# ─── WebSocket /ws/docker-metrics/{server_id} — авторизация ─────────────


def test_ws_docker_metrics_without_token_closes_1008(sync_client: TestClient):
    with pytest.raises(WebSocketDisconnect) as exc:
        with sync_client.websocket_connect("/ws/docker-metrics/1"):
            pass
    assert exc.value.code == 1008


def test_ws_docker_metrics_with_foreign_server_closes_1008(sync_client: TestClient):
    alice_token = _register_user(sync_client, "alice@example.com", "secret123")
    alice_server = _register_server(sync_client, alice_token, "alice-server")

    bob_token = _register_user(sync_client, "bob@example.com", "secret456")

    with pytest.raises(WebSocketDisconnect) as exc:
        with sync_client.websocket_connect(
            f"/ws/docker-metrics/{alice_server['id']}?token={bob_token}"
        ):
            pass
    assert exc.value.code == 1008


def test_ws_docker_metrics_valid_connection_accepted(sync_client: TestClient):
    token = _register_user(sync_client, "alice@example.com", "secret123")
    server = _register_server(sync_client, token, "srv-01")

    with sync_client.websocket_connect(
        f"/ws/docker-metrics/{server['id']}?token={token}"
    ) as ws:
        ws.send_text("ping")


# ─── Dashboard ──────────────────────────────────────────────────────────


async def test_dashboard_returns_empty_list_for_new_user(client, auth_headers):
    """Новый пользователь без серверов получает пустой дашборд."""
    response = await client.get("/servers/dashboard", headers=auth_headers)
    assert response.status_code == 200
    assert response.json() == []


async def test_dashboard_returns_server_with_latest_metric(
    client, auth_headers
):
    """Дашборд содержит последний снэпшот системных метрик."""
    # Создаём сервер
    server_resp = await client.post(
        "/servers/register",
        json={"name": "dashboard-srv"},
        headers=auth_headers,
    )
    assert server_resp.status_code == 201
    server_id = server_resp.json()["id"]
    api_key = server_resp.json()["api_key"]

    # Отправляем метрику
    await client.post(
        "/metrics",
        json={"cpu_percent": 55.5, "memory_percent": 66.6, "disk_percent": 77.7},
        headers={"X-API-Key": api_key},
    )

    # Запрашиваем дашборд
    response = await client.get("/servers/dashboard", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["id"] == server_id
    assert data[0]["name"] == "dashboard-srv"
    assert data[0]["latest_metric"] is not None
    assert data[0]["latest_metric"]["cpu_percent"] == 55.5
    assert data[0]["latest_metric"]["memory_percent"] == 66.6
    assert data[0]["latest_metric"]["disk_percent"] == 77.7


async def test_dashboard_server_without_metrics_has_none(
    client, auth_headers
):
    """Сервер без метрик — latest_metric == None."""
    server_resp = await client.post(
        "/servers/register",
        json={"name": "empty-srv"},
        headers=auth_headers,
    )
    assert server_resp.status_code == 201

    response = await client.get("/servers/dashboard", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["latest_metric"] is None
