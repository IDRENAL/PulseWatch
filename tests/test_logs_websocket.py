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


def test_dashboard_ws_without_token_closes_1008(sync_client: TestClient):
    with pytest.raises(WebSocketDisconnect) as exc:
        with sync_client.websocket_connect("/ws/logs/1"):
            pass
    assert exc.value.code == 1008


def test_dashboard_ws_with_invalid_token_closes_1008(sync_client: TestClient):
    with pytest.raises(WebSocketDisconnect) as exc:
        with sync_client.websocket_connect("/ws/logs/1?token=garbage"):
            pass
    assert exc.value.code == 1008


def test_dashboard_ws_with_unknown_server_closes_1008(sync_client: TestClient):
    token = _register_user(sync_client, "alice@example.com", "secret123")
    with pytest.raises(WebSocketDisconnect) as exc:
        with sync_client.websocket_connect(f"/ws/logs/9999?token={token}"):
            pass
    assert exc.value.code == 1008


def test_dashboard_ws_with_foreign_server_closes_1008(sync_client: TestClient):
    # Сервер заводит alice
    alice_token = _register_user(sync_client, "alice@example.com", "secret123")
    alice_server = _register_server(sync_client, alice_token, "alice-server")

    # bob пытается подписаться на её сервер
    bob_token = _register_user(sync_client, "bob@example.com", "secret456")

    with pytest.raises(WebSocketDisconnect) as exc:
        with sync_client.websocket_connect(
            f"/ws/logs/{alice_server['id']}?token={bob_token}"
        ):
            pass
    assert exc.value.code == 1008


def test_agent_ws_without_key_closes_1008(sync_client: TestClient):
    with pytest.raises(WebSocketDisconnect) as exc:
        with sync_client.websocket_connect("/ws/agent/logs"):
            pass
    assert exc.value.code == 1008


def test_agent_ws_with_invalid_key_closes_1008(sync_client: TestClient):
    with pytest.raises(WebSocketDisconnect) as exc:
        with sync_client.websocket_connect("/ws/agent/logs?api_key=not-a-key"):
            pass
    assert exc.value.code == 1008


def test_agent_ws_with_wrong_secret_closes_1008(sync_client: TestClient):
    token = _register_user(sync_client, "alice@example.com", "secret123")
    server = _register_server(sync_client, token, "web-prod-01")

    with pytest.raises(WebSocketDisconnect) as exc:
        with sync_client.websocket_connect(
            f"/ws/agent/logs?api_key={server['id']}.totally-wrong"
        ):
            pass
    assert exc.value.code == 1008


def test_agent_to_dashboard_broadcast_happy_path(sync_client: TestClient):
    token = _register_user(sync_client, "alice@example.com", "secret123")
    server = _register_server(sync_client, token, "web-prod-01")
    server_id = server["id"]
    api_key = server["api_key"]

    with sync_client.websocket_connect(
        f"/ws/logs/{server_id}?token={token}"
    ) as dashboard:
        # Дать серверной корутине дописать `manager.subscribe(...)` после accept().
        time.sleep(0.05)
        with sync_client.websocket_connect(
            f"/ws/agent/logs?api_key={api_key}"
        ) as agent:
            agent.send_text("hello from journald")
            assert dashboard.receive_text() == "hello from journald"

            agent.send_text("second line")
            assert dashboard.receive_text() == "second line"


def test_agent_broadcast_to_only_owner_dashboards(sync_client: TestClient):
    """bob не должен получать логи сервера alice."""
    alice_token = _register_user(sync_client, "alice@example.com", "secret123")
    alice_server = _register_server(sync_client, alice_token, "alice-server")
    alice_server_id = alice_server["id"]
    alice_api_key = alice_server["api_key"]

    bob_token = _register_user(sync_client, "bob@example.com", "secret456")
    bob_server = _register_server(sync_client, bob_token, "bob-server")
    bob_server_id = bob_server["id"]

    with sync_client.websocket_connect(
        f"/ws/logs/{alice_server_id}?token={alice_token}"
    ) as alice_dash:
        with sync_client.websocket_connect(
            f"/ws/logs/{bob_server_id}?token={bob_token}"
        ) as bob_dash:
            time.sleep(0.05)
            with sync_client.websocket_connect(
                f"/ws/agent/logs?api_key={alice_api_key}"
            ) as alice_agent:
                alice_agent.send_text("alice-only log")
                assert alice_dash.receive_text() == "alice-only log"

                # bob не должен получить — proверяем через короткий timeout.
                with pytest.raises(Exception):
                    # receive_text без сообщений зависнет; обернём в timeout.
                    bob_dash.receive_text(timeout=0.3)
