"""Задачи агрегации метрик."""

import asyncio
from datetime import UTC, datetime, timedelta

from loguru import logger

from app.models.metric_aggregate import PeriodType
from app.tasks.celery_app import celery_app


@celery_app.task(name="app.tasks.aggregation_tasks.task_aggregate_fivemin")
def task_aggregate_fivemin() -> None:
    """Агрегация метрик за предыдущие 5 минут."""
    now = datetime.now(UTC)
    # Округляем до начала текущего 5-минутного окна, потом откатываемся на одно окно назад.
    minute_floor = (now.minute // 5) * 5
    period_start = now.replace(minute=minute_floor, second=0, microsecond=0) - timedelta(minutes=5)
    period_end = period_start + timedelta(minutes=5)

    logger.info("Запуск 5min агрегации: {} — {}", period_start, period_end)

    asyncio.run(_run_aggregation(PeriodType.fivemin, period_start, period_end))


@celery_app.task(name="app.tasks.aggregation_tasks.task_aggregate_hourly")
def task_aggregate_hourly() -> None:
    """Агрегация метрик за предыдущий час."""
    now = datetime.now(UTC)
    period_start = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
    period_end = period_start + timedelta(hours=1)

    logger.info("Запуск hourly агрегации: {} — {}", period_start, period_end)

    asyncio.run(_run_aggregation(PeriodType.hourly, period_start, period_end))


@celery_app.task(name="app.tasks.aggregation_tasks.task_aggregate_daily")
def task_aggregate_daily() -> None:
    """Агрегация метрик за предыдущий день."""
    now = datetime.now(UTC)
    period_start = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    period_end = period_start + timedelta(days=1)

    logger.info("Запуск daily агрегации: {} — {}", period_start, period_end)

    asyncio.run(_run_aggregation(PeriodType.daily, period_start, period_end))


async def _run_aggregation(
    period_type: PeriodType, period_start: datetime, period_end: datetime
) -> None:
    """Внутренняя async-функция агрегации."""
    from app.database import async_session_factory
    from app.services.aggregation import aggregate_all_servers

    async with async_session_factory() as db:
        await aggregate_all_servers(db, period_type, period_start, period_end)
