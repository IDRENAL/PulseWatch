"""Фоновая задача обновления Gauge-метрик из БД.

Запускается в lifespan FastAPI приложения, каждые N секунд считает
ключевые числа (users, servers по статусу, open alerts) и пишет их в gauges.
"""

import asyncio
from datetime import UTC, datetime, timedelta

from loguru import logger
from sqlalchemy import func, select

from app.core.observability import open_alerts_total, servers_by_status, users_total
from app.database import async_session_factory
from app.models.alert_event import AlertEvent
from app.models.server import Server
from app.models.user import User

REFRESH_INTERVAL_SECONDS = 30
# Сервер считаем inactive если метрик нет дольше этого порога. Те же 5 мин
# что и в heartbeat-таске — важно держать в синке вручную.
INACTIVE_THRESHOLD_SECONDS = 5 * 60


async def _refresh_once() -> None:
    async with async_session_factory() as db:
        users_count = await db.scalar(select(func.count()).select_from(User))
        users_total.set(users_count or 0)

        threshold = datetime.now(UTC) - timedelta(seconds=INACTIVE_THRESHOLD_SECONDS)
        paused_q = select(func.count()).select_from(Server).where(Server.paused.is_(True))
        active_q = (
            select(func.count())
            .select_from(Server)
            .where(Server.paused.is_(False), Server.last_seen_at >= threshold)
        )
        inactive_q = (
            select(func.count())
            .select_from(Server)
            .where(
                Server.paused.is_(False),
                (Server.last_seen_at.is_(None)) | (Server.last_seen_at < threshold),
            )
        )
        servers_by_status.labels(status="paused").set((await db.scalar(paused_q)) or 0)
        servers_by_status.labels(status="active").set((await db.scalar(active_q)) or 0)
        servers_by_status.labels(status="inactive").set((await db.scalar(inactive_q)) or 0)

        open_alerts_q = (
            select(func.count()).select_from(AlertEvent).where(AlertEvent.resolved_at.is_(None))
        )
        open_alerts_total.set((await db.scalar(open_alerts_q)) or 0)


async def refresh_gauges_loop() -> None:
    """Бесконечный цикл с обработкой ошибок — одна неудачная итерация не должна
    останавливать обновления навсегда.
    """
    while True:
        try:
            await _refresh_once()
        except Exception:
            # Без traceback в проде — Loguru сам подтянет stack
            logger.exception("gauge refresh failed")
        await asyncio.sleep(REFRESH_INTERVAL_SECONDS)
