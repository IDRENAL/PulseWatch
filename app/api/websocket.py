import asyncio
from contextlib import suppress

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import authenticate_ws_agent, authenticate_ws_user
from app.core.connection_manager import manager
from app.database import get_db
from app.models.log_entry import LogEntry
from app.models.server import Server

router = APIRouter()

# Стандартный WS close code для отказа аутентификации/политики.
WS_POLICY_VIOLATION = 1008

# Параметры батч-инсерта логов агента
LOG_BATCH_MAX_SIZE = 50
LOG_BATCH_MAX_AGE_SECONDS = 1.0


@router.websocket("/ws/logs/{server_id}")
async def ws_dashboard_logs(
    websocket: WebSocket,
    server_id: int,
    token: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> None:
    user = await authenticate_ws_user(token, db)
    if user is None:
        await websocket.close(code=WS_POLICY_VIOLATION)
        return

    server_query = select(Server).where(Server.id == server_id, Server.owner_id == user.id)
    server = (await db.execute(server_query)).scalar_one_or_none()
    if server is None:
        await websocket.close(code=WS_POLICY_VIOLATION)
        return

    await websocket.accept()
    await manager.subscribe(server_id, websocket)
    try:
        # receive_text обязателен — без него WebSocketDisconnect не выкинется.
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await manager.unsubscribe(server_id, websocket)


@router.websocket("/ws/agent/logs")
async def ws_agent_logs(
    websocket: WebSocket,
    api_key: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> None:
    server = await authenticate_ws_agent(api_key, db)
    if server is None:
        await websocket.close(code=WS_POLICY_VIOLATION)
        return

    await websocket.accept()

    buffer: list[LogEntry] = []
    flush_lock = asyncio.Lock()

    async def flush() -> None:
        # Лок сериализует доступ к db.session — её нельзя использовать конкурентно
        async with flush_lock:
            if not buffer:
                return
            items = list(buffer)
            buffer.clear()
            try:
                db.add_all(items)
                await db.commit()
            except Exception as exc:
                await db.rollback()
                logger.warning("log batch persist failed ({} lines): {}", len(items), exc)

    async def periodic_flush() -> None:
        while True:
            await asyncio.sleep(LOG_BATCH_MAX_AGE_SECONDS)
            await flush()

    flush_task = asyncio.create_task(periodic_flush())
    try:
        while True:
            log_line = await websocket.receive_text()
            buffer.append(LogEntry(server_id=server.id, message=log_line))
            # Broadcast делаем сразу — для real-time выводу на дашборде батч ни к чему.
            await manager.broadcast(server.id, log_line)
            if len(buffer) >= LOG_BATCH_MAX_SIZE:
                await flush()
    except WebSocketDisconnect:
        pass
    finally:
        flush_task.cancel()
        with suppress(asyncio.CancelledError):
            await flush_task
        await flush()
