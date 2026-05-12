"""Тесты лимитов по тарифам (subscription_tier)."""

import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


def _register_and_login(client: TestClient, email: str) -> tuple[int, str]:
    """Регистрирует юзера и возвращает (user_id, access_token)."""
    reg = client.post("/auth/register", json={"email": email, "password": "secret123"})
    assert reg.status_code == 201
    user_id = reg.json()["id"]

    login = client.post(
        "/auth/login",
        data={"username": email, "password": "secret123"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    return user_id, login.json()["access_token"]


@pytest_asyncio.fixture
async def set_tier(db_session: AsyncSession):
    """Фабрика смены тарифа: await set_tier(user_id, "pro")."""

    async def _set(user_id: int, tier: str) -> None:
        await db_session.execute(
            update(User).where(User.id == user_id).values(subscription_tier=tier)
        )
        await db_session.commit()

    return _set


def test_free_tier_default_for_new_user(sync_client: TestClient):
    _, token = _register_and_login(sync_client, "default@example.com")
    response = sync_client.get("/auth/me/quota", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    body = response.json()
    assert body["tier"] == "free"
    assert body["servers_max"] == 3
    assert body["rules_max"] == 10
    assert body["servers_used"] == 0
    assert body["rules_used"] == 0


def test_server_quota_enforced_on_free_tier(sync_client: TestClient):
    _, token = _register_and_login(sync_client, "free@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    # 3 сервера допустимо
    for i in range(3):
        response = sync_client.post("/servers/register", json={"name": f"srv-{i}"}, headers=headers)
        assert response.status_code == 201, response.text

    # 4-й должен упасть в 402
    response = sync_client.post("/servers/register", json={"name": "srv-overflow"}, headers=headers)
    assert response.status_code == 402
    assert "максимум 3" in response.json()["detail"]


async def test_pro_tier_allows_more_servers(sync_client: TestClient, set_tier):
    user_id, token = _register_and_login(sync_client, "pro@example.com")
    await set_tier(user_id, "pro")
    headers = {"Authorization": f"Bearer {token}"}

    # На pro 20 серверов — проверяем что 4-й уже не падает
    for i in range(4):
        response = sync_client.post(
            "/servers/register", json={"name": f"pro-srv-{i}"}, headers=headers
        )
        assert response.status_code == 201, response.text


async def test_enterprise_tier_unlimited(sync_client: TestClient, set_tier):
    user_id, token = _register_and_login(sync_client, "ent@example.com")
    await set_tier(user_id, "enterprise")
    headers = {"Authorization": f"Bearer {token}"}

    quota = sync_client.get("/auth/me/quota", headers=headers)
    assert quota.json()["servers_max"] == -1
    assert quota.json()["rules_max"] == -1


def test_rule_quota_enforced(sync_client: TestClient):
    _, token = _register_and_login(sync_client, "rules@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    server = sync_client.post(
        "/servers/register", json={"name": "rules-srv"}, headers=headers
    ).json()
    server_id = server["id"]

    # 10 правил можно
    for i in range(10):
        response = sync_client.post(
            "/alerts/rules",
            json={
                "server_id": server_id,
                "name": f"rule-{i}",
                "metric_type": "system",
                "metric_field": "cpu_percent",
                "operator": "gt",
                "threshold_value": 50.0,
            },
            headers=headers,
        )
        assert response.status_code == 201, response.text

    # 11-е — 402
    response = sync_client.post(
        "/alerts/rules",
        json={
            "server_id": server_id,
            "name": "rule-overflow",
            "metric_type": "system",
            "metric_field": "cpu_percent",
            "operator": "gt",
            "threshold_value": 50.0,
        },
        headers=headers,
    )
    assert response.status_code == 402
    assert "максимум 10" in response.json()["detail"]
