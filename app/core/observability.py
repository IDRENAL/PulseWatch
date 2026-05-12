"""Бизнес-метрики PulseWatch для Prometheus.

prometheus-fastapi-instrumentator уже даёт HTTP-метрики (rps, latency,
status codes). Здесь — счётчики/gauges про сам продукт:
сколько метрик принято, сколько алертов открыто, сколько юзеров и т.д.

Все объекты регистрируются в дефолтном REGISTRY и автоматически попадают
в дамп `/metrics/prometheus` — никаких дополнительных эндпоинтов не нужно.
"""

from prometheus_client import Counter, Gauge

# ─── Counters — event-driven, инкремент в момент события ────────────────────

metrics_ingested_total = Counter(
    "pulsewatch_metrics_ingested_total",
    "Метрики, принятые от агентов",
    ["kind"],  # system | docker
)

logs_persisted_total = Counter(
    "pulsewatch_logs_persisted_total",
    "Строки логов, сохранённые в БД (после flush)",
)

alert_events_created_total = Counter(
    "pulsewatch_alert_events_created_total",
    "Алерт-события, созданные threshold-проверкой",
)

notifications_sent_total = Counter(
    "pulsewatch_notifications_sent_total",
    "Отправленные уведомления по каналам",
    ["channel", "status"],  # telegram|email × success|failed|skipped
)

# ─── Gauges — snapshot-метрики, обновляются периодически из лайфспана ───────

users_total = Gauge(
    "pulsewatch_users_total",
    "Количество зарегистрированных юзеров",
)

servers_by_status = Gauge(
    "pulsewatch_servers_total",
    "Серверы по статусу",
    ["status"],  # active | inactive | paused
)

open_alerts_total = Gauge(
    "pulsewatch_open_alerts_total",
    "Открытые алерт-события (resolved_at IS NULL)",
)
