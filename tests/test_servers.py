from httpx import AsyncClient


async def test_register_server_without_auth_returns_401(client: AsyncClient):
    response = await client.post("/servers/register", json={"name": "web-prod-01"})
    assert response.status_code == 401


async def test_register_server_returns_api_key_with_id_prefix(
    client: AsyncClient, auth_headers: dict[str, str]
):
    response = await client.post(
        "/servers/register",
        json={"name": "web-prod-01"},
        headers=auth_headers,
    )
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "web-prod-01"
    assert body["is_active"] is True
    assert "id" in body
    assert "api_key" in body
    assert "api_key_hash" not in body

    # Формат ключа: <server_id>.<secret>
    server_id_str, secret = body["api_key"].split(".", 1)
    assert int(server_id_str) == body["id"]
    assert len(secret) > 20


async def test_register_server_duplicate_name_returns_409(
    client: AsyncClient, auth_headers: dict[str, str]
):
    first = await client.post(
        "/servers/register",
        json={"name": "web-prod-01"},
        headers=auth_headers,
    )
    assert first.status_code == 201

    second = await client.post(
        "/servers/register",
        json={"name": "web-prod-01"},
        headers=auth_headers,
    )
    assert second.status_code == 409


async def test_my_servers_returns_only_owned(
    client: AsyncClient, auth_headers: dict[str, str]
):
    # alice регистрирует два сервера.
    await client.post(
        "/servers/register",
        json={"name": "web-prod-01"},
        headers=auth_headers,
    )
    await client.post(
        "/servers/register",
        json={"name": "web-prod-02"},
        headers=auth_headers,
    )

    response = await client.get("/servers/me", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
    names = {s["name"] for s in body}
    assert names == {"web-prod-01", "web-prod-02"}


async def test_my_servers_isolated_per_user(client: AsyncClient):
    # alice регистрируется и создаёт сервер.
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

    await client.post(
        "/servers/register",
        json={"name": "alice-server"},
        headers=alice_headers,
    )

    # bob регистрируется отдельно.
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

    bob_servers = (await client.get("/servers/me", headers=bob_headers)).json()
    assert bob_servers == []

    alice_servers = (await client.get("/servers/me", headers=alice_headers)).json()
    assert len(alice_servers) == 1
    assert alice_servers[0]["name"] == "alice-server"


async def test_my_servers_without_auth_returns_401(client: AsyncClient):
    response = await client.get("/servers/me")
    assert response.status_code == 401


async def test_different_users_can_have_same_server_name(client: AsyncClient):
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
    alice_resp = await client.post(
        "/servers/register",
        json={"name": "prod"},
        headers={"Authorization": f"Bearer {alice_token}"},
    )
    assert alice_resp.status_code == 201

    # bob — то же имя, но другой owner.
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
    bob_resp = await client.post(
        "/servers/register",
        json={"name": "prod"},
        headers={"Authorization": f"Bearer {bob_token}"},
    )
    assert bob_resp.status_code == 201
