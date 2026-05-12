"""Демо использования сгенерированного PulseWatch SDK.

Перед запуском:
1. `make up` — поднять бэкенд
2. `make sdk` — сгенерировать клиент в sdk/pulsewatch_client/
3. `python examples/use_sdk.py`

Скрипт:
- регистрирует юзера demo-sdk@example.com (или ловит 409 если уже есть)
- логинится, получает access_token
- регистрирует новый сервер
- выводит список своих серверов

Если SDK ещё не сгенерирован — будет ImportError. Это намеренно: SDK не
коммитится в git, это локальный артефакт.
"""

from __future__ import annotations

import asyncio
import sys

EMAIL = "demo-sdk@example.com"
PASSWORD = "secret123"


async def main() -> None:
    try:
        from sdk.pulsewatch_client import AuthenticatedClient, Client
        from sdk.pulsewatch_client.api.auth import (
            login_auth_login_post,
            register_user_auth_register_post,
        )
        from sdk.pulsewatch_client.api.servers import (
            list_my_servers_servers_me_get,
            register_server_servers_register_post,
        )
        from sdk.pulsewatch_client.models import (
            Body_login_auth_login_post,
            ServerCreate,
            UserCreate,
        )
    except ImportError:
        print(
            "SDK не сгенерирован. Запусти `make sdk` (бэкенд должен быть на :8000).",
            file=sys.stderr,
        )
        sys.exit(1)

    public_client = Client(base_url="http://localhost:8000")

    # 1. Регистрация (409 если уже есть — игнорируем)
    try:
        await register_user_auth_register_post.asyncio(
            client=public_client, body=UserCreate(email=EMAIL, password=PASSWORD)
        )
        print(f"✓ зарегистрирован {EMAIL}")
    except Exception as exc:
        if "409" in str(exc):
            print(f"• {EMAIL} уже зарегистрирован")
        else:
            raise

    # 2. Логин
    tokens = await login_auth_login_post.asyncio(
        client=public_client,
        body=Body_login_auth_login_post(username=EMAIL, password=PASSWORD),
    )
    print(f"✓ access_token: {tokens.access_token[:24]}…")

    auth_client = AuthenticatedClient(base_url="http://localhost:8000", token=tokens.access_token)

    # 3. Зарегистрировать сервер (с уникальным именем)
    import secrets

    name = f"sdk-demo-{secrets.token_hex(4)}"
    server = await register_server_servers_register_post.asyncio(
        client=auth_client, body=ServerCreate(name=name)
    )
    print(f"✓ создан сервер #{server.id} ({server.name}) — API key {server.api_key[:16]}…")

    # 4. Список своих серверов
    servers = await list_my_servers_servers_me_get.asyncio(client=auth_client)
    print(f"\nВсего серверов: {len(servers)}")
    for s in servers:
        print(f"  #{s.id} {s.name}: active={s.is_active}")


if __name__ == "__main__":
    asyncio.run(main())
