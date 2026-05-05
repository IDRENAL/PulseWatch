"""Тесты сервиса оценки пороговых значений."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from app.models.alert_rule import ThresholdOperator
from app.services.threshold import _compare, evaluate_docker_metrics, evaluate_system_metrics


def _make_db_mock() -> AsyncMock:
    """AsyncSession-мок: async-методы (execute/commit/refresh) — AsyncMock,
    но db.add — синхронный, иначе threshold.py создаёт корутину которая
    никогда не await'ится → RuntimeWarning.
    """
    db = AsyncMock()
    db.add = MagicMock()
    return db


# ─── _compare tests ───────────────────────────────────────────────────────


def test_compare_gt():
    assert _compare(95.0, ThresholdOperator.gt, 90.0) is True
    assert _compare(90.0, ThresholdOperator.gt, 90.0) is False
    assert _compare(85.0, ThresholdOperator.gt, 90.0) is False


def test_compare_lt():
    assert _compare(80.0, ThresholdOperator.lt, 90.0) is True
    assert _compare(90.0, ThresholdOperator.lt, 90.0) is False
    assert _compare(95.0, ThresholdOperator.lt, 90.0) is False


def test_compare_gte_equal():
    assert _compare(90.0, ThresholdOperator.gte, 90.0) is True
    assert _compare(91.0, ThresholdOperator.gte, 90.0) is True
    assert _compare(89.0, ThresholdOperator.gte, 90.0) is False


def test_compare_eq():
    assert _compare(90.0, ThresholdOperator.eq, 90.0) is True
    assert _compare(90.1, ThresholdOperator.eq, 90.0) is False


def test_compare_neq():
    assert _compare(91.0, ThresholdOperator.neq, 90.0) is True
    assert _compare(90.0, ThresholdOperator.neq, 90.0) is False


# ─── evaluate_system_metrics tests ────────────────────────────────────────


async def test_evaluate_system_metrics_triggers():
    """Правило (cpu > 90), метрика cpu=95 → срабатывание."""
    db = _make_db_mock()

    mock_rule = _make_system_rule(threshold_value=90.0, operator=ThresholdOperator.gt)
    scalars_mock = _make_scalars_mock([mock_rule])
    db.execute.return_value = scalars_mock

    with patch("app.services.threshold.publish_alert", new_callable=AsyncMock):
        events = await evaluate_system_metrics(db, server_id=1, metric_data={"cpu_percent": 95.0})

    assert len(events) == 1
    assert events[0].metric_value == 95.0
    assert events[0].threshold_value == 90.0
    assert "cpu_percent" in events[0].message
    db.add.assert_called_once()
    db.commit.assert_awaited_once()


async def test_evaluate_system_metrics_no_trigger():
    """Правило (cpu > 90), метрика cpu=80 → без срабатывания."""
    db = _make_db_mock()

    mock_rule = _make_system_rule(threshold_value=90.0, operator=ThresholdOperator.gt)
    scalars_mock = _make_scalars_mock([mock_rule])
    db.execute.return_value = scalars_mock

    events = await evaluate_system_metrics(db, server_id=1, metric_data={"cpu_percent": 80.0})

    assert len(events) == 0
    db.add.assert_not_called()
    db.commit.assert_not_awaited()


async def test_evaluate_system_metrics_cooldown():
    """Правило с last_triggered_at в пределах cooldown → без срабатывания."""
    db = _make_db_mock()

    mock_rule = _make_system_rule(
        threshold_value=90.0,
        operator=ThresholdOperator.gt,
        cooldown_seconds=300,
        last_triggered_at=datetime.now(UTC),
    )
    scalars_mock = _make_scalars_mock([mock_rule])
    db.execute.return_value = scalars_mock

    events = await evaluate_system_metrics(db, server_id=1, metric_data={"cpu_percent": 95.0})

    assert len(events) == 0
    db.add.assert_not_called()


async def test_evaluate_system_metrics_cooldown_expired():
    """Cooldown прошёл → срабатывание."""
    db = _make_db_mock()

    mock_rule = _make_system_rule(
        threshold_value=90.0,
        operator=ThresholdOperator.gt,
        cooldown_seconds=300,
        last_triggered_at=datetime.now(UTC) - timedelta(seconds=600),
    )
    scalars_mock = _make_scalars_mock([mock_rule])
    db.execute.return_value = scalars_mock

    with patch("app.services.threshold.publish_alert", new_callable=AsyncMock):
        events = await evaluate_system_metrics(db, server_id=1, metric_data={"cpu_percent": 95.0})

    assert len(events) == 1


async def test_evaluate_system_metrics_inactive_rule():
    """is_active=False → правило пропущено (фильтруется на уровне SQL)."""
    db = _make_db_mock()

    # Имитируем, что запрос к БД не возвращает правил (потому что is_active=False
    # фильтруется на уровне SQL)
    scalars_mock = _make_scalars_mock([])
    db.execute.return_value = scalars_mock

    events = await evaluate_system_metrics(db, server_id=1, metric_data={"cpu_percent": 95.0})

    assert len(events) == 0


async def test_evaluate_system_metrics_missing_field():
    """metric_field не найден в metric_data → пропущено."""
    db = _make_db_mock()

    # Правило отслеживает cpu_percent, но данные содержат только memory_percent
    mock_rule = _make_system_rule(
        metric_field="cpu_percent",
        threshold_value=90.0,
        operator=ThresholdOperator.gt,
    )
    scalars_mock = _make_scalars_mock([mock_rule])
    db.execute.return_value = scalars_mock

    events = await evaluate_system_metrics(db, server_id=1, metric_data={"memory_percent": 95.0})

    assert len(events) == 0
    db.add.assert_not_called()


# ─── evaluate_docker_metrics tests ────────────────────────────────────────


async def test_evaluate_docker_metrics_triggers():
    """Docker-правило срабатывает, когда метрика контейнера превышает порог."""
    db = _make_db_mock()

    mock_rule = _make_docker_rule(
        container_name="my_app",
        threshold_value=80.0,
        operator=ThresholdOperator.gt,
    )
    scalars_mock = _make_scalars_mock([mock_rule])
    db.execute.return_value = scalars_mock

    with patch("app.services.threshold.publish_alert", new_callable=AsyncMock):
        events = await evaluate_docker_metrics(
            db,
            server_id=1,
            container_name="my_app",
            container_data={"cpu_percent": 95.0},
        )

    assert len(events) == 1
    assert events[0].metric_value == 95.0
    assert "my_app" in events[0].message


async def test_evaluate_docker_metrics_container_filter():
    """Правило с container_name срабатывает только для совпадающего контейнера."""
    db = _make_db_mock()

    mock_rule = _make_docker_rule(
        container_name="my_app",
        threshold_value=80.0,
        operator=ThresholdOperator.gt,
    )
    scalars_mock = _make_scalars_mock([mock_rule])
    db.execute.return_value = scalars_mock

    # Другое имя контейнера — не должно срабатывать
    events = await evaluate_docker_metrics(
        db,
        server_id=1,
        container_name="other_app",
        container_data={"cpu_percent": 95.0},
    )

    assert len(events) == 0
    db.add.assert_not_called()


async def test_evaluate_docker_metrics_no_container_filter():
    """Правило без container_name применяется ко всем контейнерам."""
    db = _make_db_mock()

    mock_rule = _make_docker_rule(
        container_name=None,
        threshold_value=80.0,
        operator=ThresholdOperator.gt,
    )
    scalars_mock = _make_scalars_mock([mock_rule])
    db.execute.return_value = scalars_mock

    with patch("app.services.threshold.publish_alert", new_callable=AsyncMock):
        events = await evaluate_docker_metrics(
            db,
            server_id=1,
            container_name="any_container",
            container_data={"cpu_percent": 95.0},
        )

    assert len(events) == 1


# ─── Helpers ──────────────────────────────────────────────────────────────


def _make_system_rule(
    metric_field: str = "cpu_percent",
    threshold_value: float = 90.0,
    operator: ThresholdOperator = ThresholdOperator.gt,
    cooldown_seconds: int = 300,
    last_triggered_at: datetime | None = None,
):
    """Создаёт мок AlertRule для системных метрик."""
    rule = AsyncMock()
    rule.id = 1
    rule.server_id = 1
    rule.name = "Test Rule"
    rule.metric_type = "system"
    rule.metric_field = metric_field
    rule.operator = operator
    rule.threshold_value = threshold_value
    rule.cooldown_seconds = cooldown_seconds
    rule.is_active = True
    rule.last_triggered_at = last_triggered_at
    rule.container_name = None
    return rule


def _make_docker_rule(
    container_name: str | None = "my_app",
    metric_field: str = "cpu_percent",
    threshold_value: float = 80.0,
    operator: ThresholdOperator = ThresholdOperator.gt,
):
    """Создаёт мок AlertRule для docker-метрик."""
    rule = AsyncMock()
    rule.id = 2
    rule.server_id = 1
    rule.name = "Docker Rule"
    rule.metric_type = "docker"
    rule.metric_field = metric_field
    rule.operator = operator
    rule.threshold_value = threshold_value
    rule.cooldown_seconds = 300
    rule.is_active = True
    rule.last_triggered_at = None
    rule.container_name = container_name
    return rule


def _make_scalars_mock(items: list):
    """Создаёт мок для цепочки SQLAlchemy scalars().all().

    Реальный поток SQLAlchemy:
        result = await db.execute(...)  # возвращает CursorResult
        rules = result.scalars().all()  # scalars() синхронный, all() синхронный

    Поскольку db.execute — AsyncMock, ``await db.execute(...)`` возвращает то,
    что мы установили как return_value. Поэтому result.scalars() должен быть
    обычным Mock (не AsyncMock), возвращающим объект с .all(), возвращающим items.
    """
    from unittest.mock import MagicMock

    scalars_mock = MagicMock()
    scalars_mock.all.return_value = items

    result_mock = MagicMock()
    result_mock.scalars.return_value = scalars_mock
    return result_mock
