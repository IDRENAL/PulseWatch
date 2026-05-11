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
    try:
        while True:
            log_line = await websocket.receive_text()
            # Сохраняем + бродкастим. Commit per-line простой, но при высоком rps
            # стоило бы батчить — TODO когда упрёмся в нагрузку.
            try:
                db.add(LogEntry(server_id=server.id, message=log_line))
                await db.commit()
            except Exception as exc:
                await db.rollback()
                logger.warning("log persist failed: {}", exc)
            await manager.broadcast(server.id, log_line)
    except WebSocketDisconnect:
        pass
