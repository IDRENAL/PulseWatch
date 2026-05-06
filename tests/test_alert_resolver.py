"""Тесты авто-резолва системных алертов."""

from datetime import UTC, datetime, timedelta

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import Base
from app.models.alert_event import AlertEvent
from app.models.alert_rule import AlertRule, MetricType, ThresholdOperator
from app.models.metric import Metric
from app.models.server import Server
from app.models.user import User
from app.services.alert_resolver import auto_resolve_system_alerts


@pytest_asyncio.fixture
async def server_with_user(test_engine, db_session: AsyncSession) -> tuple[Server, User]:
    # Чистим БД перед каждым тестом — db_session фикстура сама не сбрасывает.
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    user = User(email="resolver@test.com", password_hash="x")
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    server = Server(name="srv-1", api_key_hash="h", owner_id=user.id)
    db_session.add(server)
    await db_session.commit()
    await db_session.refresh(server)
    return server, user


async def _make_rule(
    db: AsyncSession, server_id: int, owner_id: int, threshold: float = 90.0
) -> AlertRule:
    rule = AlertRule(
        server_id=server_id,
        owner_id=owner_id,
        name="cpu high",
        metric_type=MetricType.system,
        metric_field="cpu_percent",
        operator=ThresholdOperator.gt,
        threshold_value=threshold,
        cooldown_seconds=0,
        is_active=True,
    )
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    return rule


async def _make_event(
    db: AsyncSession, rule: AlertRule, server_id: int, value: float
) -> AlertEvent:
    event = AlertEvent(
        rule_id=rule.id,
        server_id=server_id,
        metric_value=value,
        threshold_value=rule.threshold_value,
        message="test",
    )
    db.add(event)
    await db.commit()
    await db.refresh(event)
    return event


async def _add_metric(
    db: AsyncSession, server_id: int, cpu: float, when: datetime | None = None
) -> Metric:
    metric = Metric(
        server_id=server_id,
        cpu_percent=cpu,
        memory_percent=10.0,
        disk_percent=10.0,
        collected_at=when or datetime.now(UTC),
    )
    db.add(metric)
    await db.commit()
    return metric


async def test_resolves_when_metric_below_threshold(db_session: AsyncSession, server_with_user):
    """Метрика упала ниже порога → событие закрывается."""
    server, user = server_with_user
    rule = await _make_rule(db_session, server.id, user.id, threshold=90.0)
    event = await _make_event(db_session, rule, server.id, value=95.0)
    await _add_metric(db_session, server.id, cpu=50.0)

    resolved = await auto_resolve_system_alerts(db_session)

    assert event.id in resolved
    await db_session.refresh(event)
    assert event.resolved_at is not None


async def test_does_not_resolve_when_metric_still_triggers(
    db_session: AsyncSession, server_with_user
):
    """Метрика всё ещё выше порога → событие открыто."""
    server, user = server_with_user
    rule = await _make_rule(db_session, server.id, user.id, threshold=90.0)
    event = await _make_event(db_session, rule, server.id, value=95.0)
    await _add_metric(db_session, server.id, cpu=92.0)

    resolved = await auto_resolve_system_alerts(db_session)

    assert event.id not in resolved
    await db_session.refresh(event)
    assert event.resolved_at is None


async def test_does_not_resolve_when_no_metrics_yet(db_session: AsyncSession, server_with_user):
    """Сервер ничего не присылал → не резолвим (статус неизвестен)."""
    server, user = server_with_user
    rule = await _make_rule(db_session, server.id, user.id, threshold=90.0)
    event = await _make_event(db_session, rule, server.id, value=95.0)

    resolved = await auto_resolve_system_alerts(db_session)

    assert event.id not in resolved
    await db_session.refresh(event)
    assert event.resolved_at is None


async def test_skips_already_resolved_events(db_session: AsyncSession, server_with_user):
    """Уже закрытые события не трогает."""
    server, user = server_with_user
    rule = await _make_rule(db_session, server.id, user.id, threshold=90.0)
    event = await _make_event(db_session, rule, server.id, value=95.0)
    event.resolved_at = datetime.now(UTC) - timedelta(hours=1)
    await db_session.commit()
    await _add_metric(db_session, server.id, cpu=50.0)

    resolved = await auto_resolve_system_alerts(db_session)

    assert event.id not in resolved


async def test_resolves_multiple_events_in_one_pass(db_session: AsyncSession, server_with_user):
    """За один проход закрывает все подходящие события."""
    server, user = server_with_user
    rule = await _make_rule(db_session, server.id, user.id, threshold=90.0)
    event1 = await _make_event(db_session, rule, server.id, value=95.0)
    event2 = await _make_event(db_session, rule, server.id, value=98.0)
    await _add_metric(db_session, server.id, cpu=50.0)

    resolved = await auto_resolve_system_alerts(db_session)

    assert set(resolved) == {event1.id, event2.id}
