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


# ─── Refresh tokens ─────────────────────────────────────────────────────────


async def _register_and_login(client: AsyncClient) -> dict:
    await client.post(
        "/auth/register", json={"email": "alice@example.com", "password": "secret123"}
    )
    r = await client.post(
        "/auth/login",
        data={"username": "alice@example.com", "password": "secret123"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    return r.json()


async def test_login_returns_refresh_token(client: AsyncClient):
    tokens = await _register_and_login(client)
    assert tokens["access_token"]
    assert tokens["refresh_token"]
    assert tokens["access_token"] != tokens["refresh_token"]


async def test_refresh_returns_new_pair(client: AsyncClient):
    tokens = await _register_and_login(client)
    response = await client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert response.status_code == 200
    new_tokens = response.json()
    assert new_tokens["access_token"]
    assert new_tokens["refresh_token"]
    # refresh обязан быть новый — там случайный jti. Access может совпасть с предыдущим,
    # если выдан в ту же секунду (exp в JWT округлён до секунд) — это норма.
    assert new_tokens["refresh_token"] != tokens["refresh_token"]


async def test_refresh_invalidates_old_token(client: AsyncClient):
    """После успешного refresh старый refresh-токен больше не работает."""
    tokens = await _register_and_login(client)
    await client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    second = await client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert second.status_code == 401


async def test_refresh_with_access_token_returns_401(client: AsyncClient):
    """Access-токен нельзя подсунуть как refresh — у него другой type."""
    tokens = await _register_and_login(client)
    response = await client.post("/auth/refresh", json={"refresh_token": tokens["access_token"]})
    assert response.status_code == 401


async def test_refresh_with_garbage_returns_401(client: AsyncClient):
    response = await client.post("/auth/refresh", json={"refresh_token": "not.a.real.jwt"})
    assert response.status_code == 401


async def test_refresh_without_body_returns_422(client: AsyncClient):
    response = await client.post("/auth/refresh", json={})
    assert response.status_code == 422


async def test_access_protected_with_refresh_token_returns_401(client: AsyncClient):
    """Refresh-токен не должен проходить как Bearer на /auth/me."""
    tokens = await _register_and_login(client)
    response = await client.get(
        "/auth/me", headers={"Authorization": f"Bearer {tokens['refresh_token']}"}
    )
    assert response.status_code == 401


async def test_logout_revokes_refresh(client: AsyncClient):
    tokens = await _register_and_login(client)
    response = await client.post("/auth/logout", json={"refresh_token": tokens["refresh_token"]})
    assert response.status_code == 204

    # Попытка использовать отозванный refresh → 401
    refreshed = await client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert refreshed.status_code == 401


async def test_logout_idempotent_with_invalid_token(client: AsyncClient):
    """Logout с битым токеном — 204 (как будто токен уже отозван)."""
    response = await client.post("/auth/logout", json={"refresh_token": "garbage"})
    assert response.status_code == 204


async def test_multiple_devices_have_independent_refresh(client: AsyncClient):
    """Логин на двух 'устройствах' даёт два независимых refresh — logout одного не валит второй."""
    await client.post(
        "/auth/register", json={"email": "alice@example.com", "password": "secret123"}
    )
    r1 = (
        await client.post(
            "/auth/login",
            data={"username": "alice@example.com", "password": "secret123"},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    ).json()
    r2 = (
        await client.post(
            "/auth/login",
            data={"username": "alice@example.com", "password": "secret123"},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    ).json()
    assert r1["refresh_token"] != r2["refresh_token"]

    # Logout первого
    await client.post("/auth/logout", json={"refresh_token": r1["refresh_token"]})

    # Второй refresh всё ещё валиден
    response = await client.post("/auth/refresh", json={"refresh_token": r2["refresh_token"]})
    assert response.status_code == 200
