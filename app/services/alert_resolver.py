"""Авто-резолв событий алертов: если последняя метрика больше не нарушает порог,
помечаем событие как закрытое (`resolved_at = now()`).

Текущая реализация резолвит ТОЛЬКО события системных правил — у `AlertEvent` нет
колонки `container_name`, поэтому связать docker-event с конкретным контейнером
без анализа `event.message` невозможно. Docker-резолв — отдельная фича.
"""

from datetime import UTC, datetime

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.alert_event import AlertEvent
from app.models.alert_rule import AlertRule, MetricType
from app.models.metric import Metric
from app.services.threshold import _compare


async def auto_resolve_system_alerts(db: AsyncSession) -> list[int]:
    """Закрывает все системные unresolved-события, у которых последняя метрика
    больше не пробивает порог.

    Returns:
        Список id закрытых событий.
    """
    # Берём только системные unresolved-события + правило к ним.
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

    # Кэш последней метрики по server_id, чтобы не дёргать БД для одного сервера
    # несколько раз, если на нём несколько активных событий.
    latest_metric_cache: dict[int, Metric | None] = {}

    for event, rule in rows:
        if event.server_id not in latest_metric_cache:
            latest_metric_cache[event.server_id] = await _get_latest_metric(db, event.server_id)

        latest = latest_metric_cache[event.server_id]
        if latest is None:
            # Сервер ничего не присылал — статус неизвестен, не резолвим
            continue

        latest_value = getattr(latest, rule.metric_field, None)
        if latest_value is None:
            # Поля такого нет в системных метриках (странно, но не падаем)
            continue

        if _compare(latest_value, rule.operator, rule.threshold_value):
            # Условие всё ещё триггерится — не резолвим
            continue

        event.resolved_at = now
        resolved_ids.append(event.id)

    if resolved_ids:
        await db.commit()
        logger.info("Auto-resolved {} alert events: ids={}", len(resolved_ids), resolved_ids)

    return resolved_ids


async def _get_latest_metric(db: AsyncSession, server_id: int) -> Metric | None:
    """Возвращает самую свежую метрику сервера или None, если их нет."""
    stmt = (
        select(Metric)
        .where(Metric.server_id == server_id)
        .order_by(Metric.collected_at.desc())
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none()
