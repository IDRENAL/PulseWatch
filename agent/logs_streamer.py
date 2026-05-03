import asyncio

import websockets
from loguru import logger
from websockets.exceptions import ConnectionClosed

from agent.collectors.logs_collector import stream_journal_logs


class LogsStreamer:
    """Гонит journald-логи в backend WS-эндпоинт с экспоненциальным backoff."""

    def __init__(
        self,
        ws_base_url: str,
        ws_path: str,
        api_key: str,
        max_backoff_seconds: float = 30.0,
    ) -> None:
        self._url = f"{ws_base_url.rstrip('/')}{ws_path}?api_key={api_key}"
        self._max_backoff = max_backoff_seconds

    async def run(self, stop_event: asyncio.Event) -> None:
        backoff = 1.0
        while not stop_event.is_set():
            try:
                async with websockets.connect(self._url) as ws:
                    logger.info("WS логов подключён")
                    backoff = 1.0  # сброс после успешного коннекта
                    async for line in stream_journal_logs():
                        if stop_event.is_set():
                            break
                        await ws.send(line)
            except asyncio.CancelledError:
                raise
            except (ConnectionClosed, OSError) as exc:
                logger.warning(
                    "WS логов оборвался: {} — реконнект через {}c", exc, backoff
                )
            except Exception as exc:
                logger.warning(
                    "WS логов: непредвиденная ошибка {} — реконнект через {}c",
                    exc,
                    backoff,
                )

            if stop_event.is_set():
                break
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=backoff)
            except asyncio.TimeoutError:
                pass
            backoff = min(backoff * 2, self._max_backoff)

        logger.info("WS логов остановлен")
