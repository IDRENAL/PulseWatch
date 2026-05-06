"""Авто-резолв событий алертов: если последняя метрика больше не нарушает порог,
помечаем событие как закрытое (`resolved_at = now()`).

Резолвит и системные, и docker-события. Для docker берёт последнюю метрику
по комбинации (server_id, container_name).
"""

from datetime import UTC, datetime

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.alert_event import AlertEvent
from app.models.alert_rule import AlertRule, MetricType
from app.models.docker_metric import DockerMetric
from app.models.metric import Metric
from app.services.threshold import _compare


async def auto_resolve_system_alerts(db: AsyncSession) -> list[int]:
    """Закрывает системные unresolved-события, у которых последняя метрика
    больше не пробивает порог.

    Returns:
        Список id закрытых событий.
    """
    stmt = (
        select(AlertEvent, AlertRule)
        .join(AlertRule, AlertEvent.rule_id == AlertRule.id)
        .where(
            AlertEvent.resolved_at.is_(None),
            AlertRule.metric_type == MetricType.system,
        )
    )
    rows = (await db.execute(stmt)).all()

    if not rows:
        return []

    now = datetime.now(UTC)
    resolved_ids: list[int] = []

    # Кэш последней метрики по server_id, чтобы не дёргать БД повторно.
    latest_metric_cache: dict[int, Metric | None] = {}

    for event, rule in rows:
        if event.server_id not in latest_metric_cache:
            latest_metric_cache[event.server_id] = await _get_latest_system_metric(
                db, event.server_id
            )

        latest = latest_metric_cache[event.server_id]
        if latest is None:
            continue

        latest_value = getattr(latest, rule.metric_field, None)
        if latest_value is None:
            continue

        if _compare(latest_value, rule.operator, rule.threshold_value):
            continue

        event.resolved_at = now
        resolved_ids.append(event.id)

    if resolved_ids:
        await db.commit()
        logger.info("Auto-resolved {} system alerts: ids={}", len(resolved_ids), resolved_ids)

    return resolved_ids


async def auto_resolve_docker_alerts(db: AsyncSession) -> list[int]:
    """Закрывает docker unresolved-события, у которых последняя метрика
    конкретного контейнера больше не пробивает порог.

    Если у события нет container_name (старые события до миграции) — пропускаем.

    Returns:
        Список id закрытых событий.
    """
    stmt = (
        select(AlertEvent, AlertRule)
        .join(AlertRule, AlertEvent.rule_id == AlertRule.id)
        .where(
            AlertEvent.resolved_at.is_(None),
            AlertRule.metric_type == MetricType.docker,
            AlertEvent.container_name.is_not(None),
        )
    )
    rows = (await db.execute(stmt)).all()

    if not rows:
        return []

    now = datetime.now(UTC)
    resolved_ids: list[int] = []

    # Кэш по (server_id, container_name)
    latest_cache: dict[tuple[int, str], DockerMetric | None] = {}

    for event, rule in rows:
        # Тип уже отфильтрован в WHERE, но mypy не знает
        assert event.container_name is not None
        key = (event.server_id, event.container_name)

        if key not in latest_cache:
            latest_cache[key] = await _get_latest_docker_metric(db, *key)

        latest = latest_cache[key]
        if latest is None:
            continue

        latest_value = getattr(latest, rule.metric_field, None)
        if latest_value is None:
            continue

        if _compare(latest_value, rule.operator, rule.threshold_value):
            continue

        event.resolved_at = now
        resolved_ids.append(event.id)

    if resolved_ids:
        await db.commit()
        logger.info("Auto-resolved {} docker alerts: ids={}", len(resolved_ids), resolved_ids)

    return resolved_ids


async def _get_latest_system_metric(db: AsyncSession, server_id: int) -> Metric | None:
    """Возвращает самую свежую системную метрику сервера или None."""
    stmt = (
        select(Metric)
        .where(Metric.server_id == server_id)
        .order_by(Metric.collected_at.desc())
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def _get_latest_docker_metric(
    db: AsyncSession, server_id: int, container_name: str
) -> DockerMetric | None:
    """Возвращает самую свежую docker-метрику конкретного контейнера или None."""
    stmt = (
        select(DockerMetric)
        .where(
            DockerMetric.server_id == server_id,
            DockerMetric.container_name == container_name,
        )
        .order_by(DockerMetric.collected_at.desc())
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none()
