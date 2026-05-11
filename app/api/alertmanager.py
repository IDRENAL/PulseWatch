"""Webhook-приёмник от Alertmanager.

Alertmanager шлёт сюда сгруппированные алерты по схеме v4
(https://prometheus.io/docs/alerting/latest/configuration/#webhook_config).
Мы их просто логируем — никакой пер-юзер маршрутизации, потому что это
инфраструктурные алерты (бэкенд лежит / много 5xx). Видны в `docker compose logs app`.

Сетевая безопасность: эндпоинт открыт без auth, но Alertmanager в compose-сети
ходит к app по внутреннему DNS, наружу 9093 публикуется только для Web-UI.
Если выкладывать в прод — закрой /alertmanager/webhook через nginx / basic-auth.
"""

from typing import Any

from fastapi import APIRouter, status
from loguru import logger

router = APIRouter()


@router.post("/webhook", status_code=status.HTTP_204_NO_CONTENT)
async def receive_alertmanager_webhook(payload: dict[str, Any]) -> None:
    """Принимает POST от Alertmanager и логирует каждый алерт.

    Тело: {"status": "firing"|"resolved", "alerts": [{"status", "labels", "annotations", ...}], ...}
    """
    overall_status = payload.get("status", "?")
    alerts = payload.get("alerts", [])
    logger.info(
        "alertmanager webhook: status={} count={} group_key={}",
        overall_status,
        len(alerts),
        payload.get("groupKey", "?"),
    )
    for alert in alerts:
        labels = alert.get("labels", {}) or {}
        annotations = alert.get("annotations", {}) or {}
        logger.info(
            "  [{}] {} (severity={}): {}",
            alert.get("status", "?"),
            labels.get("alertname", "?"),
            labels.get("severity", "?"),
            annotations.get("summary") or annotations.get("description", ""),
        )
