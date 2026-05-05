from httpx import AsyncClient


async def test_register_creates_user(client: AsyncClient):
    response = await client.post(
        "/auth/register",
        json={"email": "alice@example.com", "password": "secret123"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "alice@example.com"
    assert body["is_active"] is True
    assert "id" in body
    assert "password_hash" not in body


async def test_register_duplicate_email_returns_409(client: AsyncClient):
    payload = {"email": "alice@example.com", "password": "secret123"}
    first = await client.post("/auth/register", json=payload)
    assert first.status_code == 201

    second = await client.post("/auth/register", json=payload)
    assert second.status_code == 409


async def test_login_with_correct_password_returns_token(client: AsyncClient):
    await client.post(
        "/auth/register",
        json={"email": "alice@example.com", "password": "secret123"},
    )
    response = await client.post(
        "/auth/login",
        data={"username": "alice@example.com", "password": "secret123"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]


async def test_login_with_wrong_password_returns_401(client: AsyncClient):
    await client.post(
        "/auth/register",
        json={"email": "alice@example.com", "password": "secret123"},
    )
    response = await client.post(
        "/auth/login",
        data={"username": "alice@example.com", "password": "wrong"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 401


async def test_login_unknown_user_returns_401(client: AsyncClient):
    response = await client.post(
        "/auth/login",
        data={"username": "ghost@example.com", "password": "irrelevant"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 401


async def test_me_with_valid_token_returns_user(client: AsyncClient, auth_headers: dict[str, str]):
    response = await client.get("/auth/me", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "alice@example.com"


async def test_me_without_token_returns_401(client: AsyncClient):
    response = await client.get("/auth/me")
    assert response.status_code == 401


async def test_me_with_broken_token_returns_401(client: AsyncClient):
    response = await client.get("/auth/me", headers={"Authorization": "Bearer not.a.real.jwt"})
    assert response.status_code == 401
