# PulseWatch Python SDK

Тонкий типизированный HTTP-клиент, **сгенерированный из OpenAPI-схемы**
бэкенда через [`openapi-python-client`](https://github.com/openapi-generators/openapi-python-client).
Сам код клиента в `sdk/pulsewatch_client/` не коммитится — гитигнор;
генерируется по запросу.

## Сгенерировать клиент

Бэкенд должен быть запущен (`make up`) — клиент берётся из живого
`/openapi.json`:

```bash
make sdk
```

Под капотом:

```bash
uvx openapi-python-client@latest generate \
    --url http://localhost:8000/openapi.json \
    --output-path sdk/pulsewatch_client \
    --overwrite \
    --meta none
```

Получишь:

```
sdk/pulsewatch_client/
├── api/             # модули по тегам (auth/, servers/, alerts/, ...)
├── models/          # Pydantic-эквиваленты pulsewatch-схем
├── client.py        # AuthenticatedClient + Client (httpx Async)
├── errors.py
└── types.py
```

## Использовать

```python
import asyncio
from sdk.pulsewatch_client import AuthenticatedClient
from sdk.pulsewatch_client.api.auth import login_auth_login_post
from sdk.pulsewatch_client.api.servers import list_my_servers_servers_me_get
from sdk.pulsewatch_client.models import Body_login_auth_login_post

async def main():
    # 1. Login (без аутентификации)
    from sdk.pulsewatch_client import Client
    client = Client(base_url="http://localhost:8000")
    tokens = await login_auth_login_post.asyncio(
        client=client,
        body=Body_login_auth_login_post(
            username="me@example.com",
            password="secret123",
        ),
    )
    print("access_token:", tokens.access_token)

    # 2. Дальше — с токеном
    auth_client = AuthenticatedClient(
        base_url="http://localhost:8000",
        token=tokens.access_token,
    )
    servers = await list_my_servers_servers_me_get.asyncio(client=auth_client)
    for s in servers:
        print(s.id, s.name, s.is_active)

asyncio.run(main())
```

См. `examples/use_sdk.py` для готового сниппета.

## Версионирование

OpenAPI-схема включает и `/v1/...` и legacy-роуты (помеченные `deprecated`).
По умолчанию генерируются оба набора функций — выбирай те, что под `/v1/`.

## Когда генерировать заново

После любого изменения API (новые эндпоинты, поля, типы) — перегенерируй
SDK через `make sdk`. На CI можно добавить шаг, который генерирует и
сверяет diff (опционально).
