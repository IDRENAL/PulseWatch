"""Задача мониторинга heartbeat серверов."""
import asyncio
from datetime import datetime, timezone, timedelta

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
    from app.database import async_session_factory
    from app.models.server import Server
    from sqlalchemy import select, update

    threshold = datetime.now(timezone.utc) - timedelta(minutes=5)

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
        await db.execute(
            update(Server)
            .where(Server.last_seen_at >= threshold, Server.is_active == False)
            .values(is_active=True)
            .returning(Server.id, Server.name)
        )

        await db.commit()

        for server_id, name in deactivated:
            logger.warning("Сервер '{}' (id={}) помечен как неактивный", name, server_id)
