"""Smoke-tests: /v1/... префикс доступен наряду с legacy путями."""

from fastapi.testclient import TestClient


def test_health_unversioned_still_works(sync_client: TestClient):
    """Корневой /health не версионируется, остаётся доступным."""
    response = sync_client.get("/health")
    assert response.status_code == 200


def test_auth_register_legacy_path(sync_client: TestClient):
    response = sync_client.post(
        "/auth/register",
        json={"email": "legacy@example.com", "password": "secret123"},
    )
    assert response.status_code == 201


def test_auth_register_v1_path(sync_client: TestClient):
    response = sync_client.post(
        "/v1/auth/register",
        json={"email": "v1@example.com", "password": "secret123"},
    )
    assert response.status_code == 201


def test_login_works_via_v1(sync_client: TestClient):
    sync_client.post(
        "/v1/auth/register",
        json={"email": "user@example.com", "password": "secret123"},
    )
    response = sync_client.post(
        "/v1/auth/login",
        data={"username": "user@example.com", "password": "secret123"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 200
    assert "access_token" in response.json()


def test_v1_and_legacy_share_auth_token(sync_client: TestClient):
    """Токен, выданный через /v1/auth/login, валиден на legacy /auth/me."""
    sync_client.post(
        "/v1/auth/register",
        json={"email": "share@example.com", "password": "secret123"},
    )
    login = sync_client.post(
        "/v1/auth/login",
        data={"username": "share@example.com", "password": "secret123"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    token = login.json()["access_token"]
    response = sync_client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.json()["email"] == "share@example.com"
