import asyncio

from fastapi import WebSocket
from loguru import logger


class LogsConnectionManager:
    """In-memory реестр подписчиков-дашбордов на лог-стрим конкретного server_id."""

    def __init__(self) -> None:
        self._subscribers: dict[int, set[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def subscribe(self, server_id: int, websocket: WebSocket) -> None:
        async with self._lock:
            self._subscribers.setdefault(server_id, set()).add(websocket)

    async def unsubscribe(self, server_id: int, websocket: WebSocket) -> None:
        async with self._lock:
            subs = self._subscribers.get(server_id)
            if subs is None:
                return
            subs.discard(websocket)
            if not subs:
                self._subscribers.pop(server_id, None)

    async def broadcast(self, server_id: int, message: str) -> None:
        # Снимаем снимок под локом и сразу отпускаем — рассылка идёт без лока,
        # иначе медленный клиент блокирует subscribe/unsubscribe всем остальным.
        async with self._lock:
            targets = list(self._subscribers.get(server_id, ()))

        if not targets:
            return

        failed: list[WebSocket] = []
        for ws in targets:
            try:
                await ws.send_text(message)
            except Exception as exc:
                logger.warning(
                    "Не удалось отправить лог подписчику server_id={}: {}",
                    server_id,
                    exc,
                )
                failed.append(ws)

        if failed:
            async with self._lock:
                subs = self._subscribers.get(server_id)
                if subs is not None:
                    for ws in failed:
                        subs.discard(ws)
                    if not subs:
                        self._subscribers.pop(server_id, None)


manager = LogsConnectionManager()
