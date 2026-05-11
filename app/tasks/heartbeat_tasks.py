"""Задача мониторинга heartbeat серверов."""

import asyncio
from datetime import UTC, datetime, timedelta

from loguru import logger

from app.tasks.celery_app import celery_app


@celery_app.task(name="app.tasks.heartbeat_tasks.task_check_heartbeat")
def task_check_heartbeat() -> None:
    """
    Проверяет активность серверов.
    Если сервер не отправлял метрики более 5 минут — помечает как неактивный.
    """
    asyncio.run(_run_heartbeat_check())


async def _run_heartbeat_check() -> None:
    """Внутренняя async-функция проверки heartbeat."""
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.models.server import Server
    from app.tasks.notification_tasks import send_heartbeat_down, send_heartbeat_recovery

    threshold = datetime.now(UTC) - timedelta(minutes=5)

    async with async_session_factory() as db:
        # Помечаем неактивные серверы
        result = await db.execute(
            update(Server)
            .where(Server.last_seen_at < threshold, Server.is_active == True)
            .values(is_active=False)
            .returning(Server.id, Server.name)
        )
        deactivated = result.all()

        # Помечаем активные серверы (если снова появились)
        result = await db.execute(
            update(Server)
            .where(Server.last_seen_at >= threshold, Server.is_active == False)
            .values(is_active=True)
            .returning(Server.id, Server.name)
        )
        recovered = result.all()

        await db.commit()

        for server_id, name in deactivated:
            logger.warning("Сервер '{}' (id={}) помечен как неактивный", name, server_id)
            send_heartbeat_down.delay(server_id)

        for server_id, name in recovered:
            logger.info("Сервер '{}' (id={}) снова активен", name, server_id)
            send_heartbeat_recovery.delay(server_id)
