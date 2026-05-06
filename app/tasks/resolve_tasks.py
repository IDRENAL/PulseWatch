"""Задачи авто-резолва алертов."""

import asyncio

from loguru import logger

from app.tasks.celery_app import celery_app


@celery_app.task(name="app.tasks.resolve_tasks.task_resolve_alerts")
def task_resolve_alerts() -> None:
    """Авто-резолв активных событий (system + docker), у которых последняя
    метрика больше не нарушает порог. Запускается периодически из Beat.
    """
    logger.info("Запуск auto_resolve (system + docker)")
    asyncio.run(_run())


async def _run() -> None:
    from app.database import async_session_factory
    from app.services.alert_resolver import (
        auto_resolve_docker_alerts,
        auto_resolve_system_alerts,
    )

    async with async_session_factory() as db:
        await auto_resolve_system_alerts(db)
        await auto_resolve_docker_alerts(db)
