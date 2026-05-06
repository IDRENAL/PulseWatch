from datetime import UTC, datetime

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.alert_event import AlertEvent
from app.models.alert_rule import AlertRule, MetricType, ThresholdOperator
from app.redis_client import publish_alert


def _enqueue_telegram_alert(event_id: int) -> None:
    """Ставит задачу отправки Telegram-уведомления в Celery-очередь.

    Импорт лежит внутри функции, чтобы не тянуть Celery (и Redis-клиент брокера)
    в код, который тестируется без воркера. Best-effort — если очередь недоступна,
    лог и идём дальше: создание события важнее доставки уведомления.
    """
    try:
        from app.tasks.notification_tasks import send_telegram_alert

        send_telegram_alert.delay(event_id)
    except Exception as exc:
        logger.warning("Failed to enqueue telegram alert for event_id={}: {}", event_id, exc)


def _compare(actual: float, operator: ThresholdOperator, threshold: float) -> bool:
    ops = {
        ThresholdOperator.gt: lambda a, t: a > t,
        ThresholdOperator.gte: lambda a, t: a >= t,
        ThresholdOperator.lt: lambda a, t: a < t,
        ThresholdOperator.lte: lambda a, t: a <= t,
        ThresholdOperator.eq: lambda a, t: a == t,
        ThresholdOperator.neq: lambda a, t: a != t,
    }
    return ops[operator](actual, threshold)


async def evaluate_system_metrics(
    db: AsyncSession, server_id: int, metric_data: dict
) -> list[AlertEvent]:
    """
    Проверяет системные метрики против всех активных правил.
    metric_data = {"cpu_percent": ..., "memory_percent": ..., "disk_percent": ...}
    Возвращает список созданных AlertEvent.
    """
    rules_result = await db.execute(
        select(AlertRule).where(
            AlertRule.server_id == server_id,
            AlertRule.metric_type == MetricType.system,
            AlertRule.is_active == True,
        )
    )
    rules = rules_result.scalars().all()

    now = datetime.now(UTC)
    # Список кортежей (event, rule) для корректной публикации
    pending: list[tuple[AlertEvent, AlertRule]] = []

    for rule in rules:
        value = metric_data.get(rule.metric_field)
        if value is None:
            continue

        if not _compare(value, rule.operator, rule.threshold_value):
            continue

        # Проверка cooldown
        if rule.last_triggered_at is not None:
            elapsed = (now - rule.last_triggered_at).total_seconds()
            if elapsed < rule.cooldown_seconds:
                continue

        # Создание события
        event = AlertEvent(
            rule_id=rule.id,
            server_id=server_id,
            metric_value=value,
            threshold_value=rule.threshold_value,
            message=(
                f"{rule.name}: {rule.metric_field}={value} "
                f"{rule.operator.value} {rule.threshold_value}"
            ),
        )
        db.add(event)
        rule.last_triggered_at = now
        pending.append((event, rule))

    if pending:
        await db.commit()
        for event, rule in pending:
            await db.refresh(event)
            _enqueue_telegram_alert(event.id)
            # Публикация в Redis (best-effort)
            try:
                await publish_alert(
                    server_id=server_id,
                    data={
                        "event_id": event.id,
                        "rule_id": event.rule_id,
                        "rule_name": rule.name,
                        "metric_value": event.metric_value,
                        "threshold_value": event.threshold_value,
                        "message": event.message,
                        "created_at": event.created_at.isoformat(),
                    },
                )
            except Exception:
                pass  # Redis failure не должен блокировать

    return [event for event, _ in pending]


async def evaluate_docker_metrics(
    db: AsyncSession, server_id: int, container_name: str, container_data: dict
) -> list[AlertEvent]:
    """
    Проверяет docker-метрики контейнера против всех активных правил.
    container_data = {"cpu_percent": ..., "memory_usage": ..., ...}
    Возвращает список созданных AlertEvent.
    """
    rules_result = await db.execute(
        select(AlertRule).where(
            AlertRule.server_id == server_id,
            AlertRule.metric_type == MetricType.docker,
            AlertRule.is_active == True,
        )
    )
    rules = rules_result.scalars().all()

    now = datetime.now(UTC)
    # Список кортежей (event, rule) для корректной публикации
    pending: list[tuple[AlertEvent, AlertRule]] = []

    for rule in rules:
        # Если у правила есть фильтр container_name, проверяем совпадение
        if rule.container_name is not None and rule.container_name != container_name:
            continue

        value = container_data.get(rule.metric_field)
        if value is None:
            continue

        if not _compare(value, rule.operator, rule.threshold_value):
            continue

        # Проверка cooldown
        if rule.last_triggered_at is not None:
            elapsed = (now - rule.last_triggered_at).total_seconds()
            if elapsed < rule.cooldown_seconds:
                continue

        event = AlertEvent(
            rule_id=rule.id,
            server_id=server_id,
            metric_value=value,
            threshold_value=rule.threshold_value,
            container_name=container_name,
            message=(
                f"{rule.name}: {container_name} {rule.metric_field}={value} "
                f"{rule.operator.value} {rule.threshold_value}"
            ),
        )
        db.add(event)
        rule.last_triggered_at = now
        pending.append((event, rule))

    if pending:
        await db.commit()
        for event, rule in pending:
            await db.refresh(event)
            _enqueue_telegram_alert(event.id)
            try:
                await publish_alert(
                    server_id=server_id,
                    data={
                        "event_id": event.id,
                        "rule_id": event.rule_id,
                        "rule_name": rule.name,
                        "container_name": container_name,
                        "metric_value": event.metric_value,
                        "threshold_value": event.threshold_value,
                        "message": event.message,
                        "created_at": event.created_at.isoformat(),
                    },
                )
            except Exception:
                pass

    return [event for event, _ in pending]
