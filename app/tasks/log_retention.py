"""Celery-задача: чистит таблицу logs от записей старше LOG_RETENTION_DAYS."""

import asyncio
from datetime import UTC, datetime, timedelta

from loguru import logger
from sqlalchemy import delete

from app.config import settings
from app.tasks.celery_app import celery_app


@celery_app.task(name="app.tasks.log_retention.task_prune_old_logs")
def task_prune_old_logs() -> None:
    """Удаляет строки logs.created_at < now - LOG_RETENTION_DAYS."""
    asyncio.run(_run())


async def _run() -> None:
    from app.database import async_session_factory
    from app.models.log_entry import LogEntry

    threshold = datetime.now(UTC) - timedelta(days=settings.log_retention_days)
    async with async_session_factory() as db:
        result = await db.execute(delete(LogEntry).where(LogEntry.created_at < threshold))
        await db.commit()
        rowcount = getattr(result, "rowcount", -1)
        logger.info("log retention: deleted {} rows older than {}", rowcount, threshold)
