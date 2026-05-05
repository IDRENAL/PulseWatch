"""Сервис агрегации метрик."""

import logging
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.docker_aggregate import DockerAggregate
from app.models.docker_metric import DockerMetric
from app.models.metric import Metric
from app.models.metric_aggregate import MetricAggregate, PeriodType
from app.models.server import Server

logger = logging.getLogger(__name__)


async def aggregate_system_metrics(
    db: AsyncSession,
    server_id: int,
    period_type: PeriodType,
    period_start: datetime,
    period_end: datetime,
) -> MetricAggregate | None:
    """
    Агрегирует сырые системные метрики за период [period_start, period_end).
    Использует UPSERT (INSERT ON CONFLICT DO UPDATE).
    """
    # Получаем агрегированные значения из сырых метрик
    result = await db.execute(
        select(
            func.avg(Metric.cpu_percent).label("avg_cpu"),
            func.min(Metric.cpu_percent).label("min_cpu"),
            func.max(Metric.cpu_percent).label("max_cpu"),
            func.avg(Metric.memory_percent).label("avg_memory"),
            func.min(Metric.memory_percent).label("min_memory"),
            func.max(Metric.memory_percent).label("max_memory"),
            func.avg(Metric.disk_percent).label("avg_disk"),
            func.min(Metric.disk_percent).label("min_disk"),
            func.max(Metric.disk_percent).label("max_disk"),
            func.count(Metric.id).label("sample_count"),
        ).where(
            Metric.server_id == server_id,
            Metric.collected_at >= period_start,
            Metric.collected_at < period_end,
        )
    )
    row = result.one()

    if row.sample_count == 0:
        logger.info("Нет данных для агрегации server_id=%s period=%s", server_id, period_type)
        return None

    # UPSERT через PostgreSQL INSERT ON CONFLICT
    stmt = pg_insert(MetricAggregate).values(
        server_id=server_id,
        period_type=period_type,
        period_start=period_start,
        period_end=period_end,
        avg_cpu=row.avg_cpu,
        min_cpu=row.min_cpu,
        max_cpu=row.max_cpu,
        avg_memory=row.avg_memory,
        min_memory=row.min_memory,
        max_memory=row.max_memory,
        avg_disk=row.avg_disk,
        min_disk=row.min_disk,
        max_disk=row.max_disk,
        sample_count=row.sample_count,
    )

    stmt = stmt.on_conflict_do_update(
        constraint="uq_metric_agg_server_period",
        set_={
            "avg_cpu": stmt.excluded.avg_cpu,
            "min_cpu": stmt.excluded.min_cpu,
            "max_cpu": stmt.excluded.max_cpu,
            "avg_memory": stmt.excluded.avg_memory,
            "min_memory": stmt.excluded.min_memory,
            "max_memory": stmt.excluded.max_memory,
            "avg_disk": stmt.excluded.avg_disk,
            "min_disk": stmt.excluded.min_disk,
            "max_disk": stmt.excluded.max_disk,
            "sample_count": stmt.excluded.sample_count,
            "updated_at": func.now(),
        },
    )

    await db.execute(stmt)
    await db.commit()

    # Получаем созданную/обновлённую запись
    agg = (
        await db.execute(
            select(MetricAggregate).where(
                MetricAggregate.server_id == server_id,
                MetricAggregate.period_type == period_type,
                MetricAggregate.period_start == period_start,
            )
        )
    ).scalar_one()

    logger.info(
        "Агрегация system server_id=%s %s: %d samples",
        server_id,
        period_type,
        row.sample_count,
    )
    return agg


async def aggregate_docker_metrics(
    db: AsyncSession,
    server_id: int,
    period_type: PeriodType,
    period_start: datetime,
    period_end: datetime,
) -> list[DockerAggregate]:
    """
    Агрегирует сырые Docker-метрики за период [period_start, period_end).
    Группирует по container_name. UPSERT для каждого контейнера.
    """
    # Получаем список контейнеров за период
    containers_result = await db.execute(
        select(DockerMetric.container_name)
        .where(
            DockerMetric.server_id == server_id,
            DockerMetric.collected_at >= period_start,
            DockerMetric.collected_at < period_end,
        )
        .distinct()
    )
    container_names = [row[0] for row in containers_result.all()]

    if not container_names:
        logger.info("Нет docker-данных для агрегации server_id=%s", server_id)
        return []

    aggregates = []
    for container_name in container_names:
        result = await db.execute(
            select(
                func.avg(DockerMetric.cpu_percent).label("avg_cpu"),
                func.min(DockerMetric.cpu_percent).label("min_cpu"),
                func.max(DockerMetric.cpu_percent).label("max_cpu"),
                func.avg(DockerMetric.memory_usage_mb).label("avg_memory_usage"),
                func.max(DockerMetric.memory_usage_mb).label("max_memory_usage"),
                func.count(DockerMetric.id).label("sample_count"),
            ).where(
                DockerMetric.server_id == server_id,
                DockerMetric.container_name == container_name,
                DockerMetric.collected_at >= period_start,
                DockerMetric.collected_at < period_end,
            )
        )
        row = result.one()

        if row.sample_count == 0:
            continue

        stmt = pg_insert(DockerAggregate).values(
            server_id=server_id,
            container_name=container_name,
            period_type=period_type,
            period_start=period_start,
            period_end=period_end,
            avg_cpu=row.avg_cpu,
            min_cpu=row.min_cpu,
            max_cpu=row.max_cpu,
            avg_memory_usage=row.avg_memory_usage,
            max_memory_usage=row.max_memory_usage,
            total_rx_bytes=0,  # зарезервировано
            total_tx_bytes=0,  # зарезервировано
            sample_count=row.sample_count,
        )

        stmt = stmt.on_conflict_do_update(
            constraint="uq_docker_agg_container_period",
            set_={
                "avg_cpu": stmt.excluded.avg_cpu,
                "min_cpu": stmt.excluded.min_cpu,
                "max_cpu": stmt.excluded.max_cpu,
                "avg_memory_usage": stmt.excluded.avg_memory_usage,
                "max_memory_usage": stmt.excluded.max_memory_usage,
                "total_rx_bytes": stmt.excluded.total_rx_bytes,
                "total_tx_bytes": stmt.excluded.total_tx_bytes,
                "sample_count": stmt.excluded.sample_count,
                "updated_at": func.now(),
            },
        )

        await db.execute(stmt)

        # Получаем созданную/обновлённую запись
        agg = (
            await db.execute(
                select(DockerAggregate).where(
                    DockerAggregate.server_id == server_id,
                    DockerAggregate.container_name == container_name,
                    DockerAggregate.period_type == period_type,
                    DockerAggregate.period_start == period_start,
                )
            )
        ).scalar_one()
        aggregates.append(agg)

    await db.commit()
    logger.info(
        "Агрегация docker server_id=%s %s: %d containers",
        server_id,
        period_type,
        len(aggregates),
    )
    return aggregates


async def aggregate_all_servers(
    db: AsyncSession,
    period_type: PeriodType,
    period_start: datetime,
    period_end: datetime,
) -> None:
    """Агрегирует метрики всех серверов за указанный период."""
    servers_result = await db.execute(select(Server.id))
    server_ids = [row[0] for row in servers_result.all()]

    for sid in server_ids:
        try:
            await aggregate_system_metrics(db, sid, period_type, period_start, period_end)
            await aggregate_docker_metrics(db, sid, period_type, period_start, period_end)
        except Exception as e:
            logger.error("Ошибка агрегации server_id=%s: %s", sid, e)
            continue
