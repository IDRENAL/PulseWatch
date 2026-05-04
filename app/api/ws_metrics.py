import asyncio

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import authenticate_ws_user
from app.database import get_db
from app.models.server import Server
from app.redis_client import get_redis

router = APIRouter()

WS_POLICY_VIOLATION = 1008


async def _ws_subscribe(
    websocket: WebSocket,
    server_id: int,
    token: str | None,
    channel_prefix: str,
    db: AsyncSession,
) -> None:
    """
    Общая логика WebSocket-подписки на Redis Pub/Sub канал.

    1. Аутентифицирует пользователя по JWT (query param ``token``).
    2. Проверяет владение сервером.
    3. Подписывается на Redis-канал ``{channel_prefix}:{server_id}``
       и транслирует сообщения в WebSocket.
    """
    # Аутентификация + проверка владения
    user = await authenticate_ws_user(token, db)
    if user is None:
        await websocket.close(code=WS_POLICY_VIOLATION)
        return

    server_query = select(Server).where(
        Server.id == server_id, Server.owner_id == user.id
    )
    server = (await db.execute(server_query)).scalar_one_or_none()
    if server is None:
        await websocket.close(code=WS_POLICY_VIOLATION)
        return

    await websocket.accept()

    redis = get_redis()
    pubsub = redis.pubsub()
    channel_name = f"{channel_prefix}:{server_id}"

    try:
        await pubsub.subscribe(channel_name)

        # Задача: читаем из Redis Pub/Sub и отправляем в WebSocket
        async def listen_redis():
            async for message in pubsub.listen():
                if message["type"] == "message":
                    data = message["data"]
                    if isinstance(data, bytes):
                        data = data.decode("utf-8")
                    try:
                        await websocket.send_text(data)
                    except Exception:
                        break

        # Задача: читаем из WebSocket, чтобы обнаружить дисконнект
        async def listen_ws():
            try:
                while True:
                    await websocket.receive_text()
            except WebSocketDisconnect:
                pass

        listen_task = asyncio.create_task(listen_redis())
        ws_task = asyncio.create_task(listen_ws())

        # Ждём завершения любой задачи (дисконнект или ошибка)
        done, pending = await asyncio.wait(
            [listen_task, ws_task], return_when=asyncio.FIRST_COMPLETED
        )

        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)

    except Exception as exc:
        logger.warning(
            "WS {} error for server_id={}: {}", channel_prefix, server_id, exc
        )
    finally:
        await pubsub.unsubscribe(channel_name)
        await pubsub.aclose()


@router.websocket("/ws/metrics/{server_id}")
async def ws_metrics(
    websocket: WebSocket,
    server_id: int,
    token: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> None:
    """
    WebSocket для real-time системных метрик.
    Клиент подписывается на Redis-канал metrics:{server_id}
    и получает данные мгновенно при публикации агентом.
    """
    await _ws_subscribe(websocket, server_id, token, "metrics", db)


@router.websocket("/ws/docker-metrics/{server_id}")
async def ws_docker_metrics(
    websocket: WebSocket,
    server_id: int,
    token: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> None:
    """
    WebSocket для real-time Docker-метрик.
    Клиент подписывается на Redis-канал docker_metrics:{server_id}.
    """
    await _ws_subscribe(websocket, server_id, token, "docker_metrics", db)


@router.websocket("/ws/alerts/{server_id}")
async def ws_alerts(
    websocket: WebSocket,
    server_id: int,
    token: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> None:
    """
    WebSocket для real-time алерт-уведомлений.
    Клиент подписывается на Redis-канал alerts:{server_id}.
    """
    await _ws_subscribe(websocket, server_id, token, "alerts", db)
