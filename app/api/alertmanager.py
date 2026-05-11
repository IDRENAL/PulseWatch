"""Webhook-приёмник от Alertmanager.

Alertmanager шлёт сюда сгруппированные алерты по схеме v4
(https://prometheus.io/docs/alerting/latest/configuration/#webhook_config).
Мы логируем каждый алерт и, если задан `ADMIN_TELEGRAM_CHAT_ID`, дублируем
в Telegram админу.

Сетевая безопасность: эндпоинт открыт без auth, но Alertmanager в compose-сети
ходит к app по внутреннему DNS, наружу 9093 публикуется только для Web-UI.
Если выкладывать в прод — закрой /alertmanager/webhook через nginx / basic-auth.
"""

import html
from typing import Any

from fastapi import APIRouter, status
from loguru import logger

from app.config import settings
from app.services.telegram import TelegramNotConfiguredError, TelegramSendError, send_message

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

    if settings.admin_telegram_chat_id and alerts:
        message = _format_admin_message(overall_status, alerts)
        try:
            await send_message(settings.admin_telegram_chat_id, message)
        except (TelegramNotConfiguredError, TelegramSendError) as exc:
            logger.warning("alertmanager → admin telegram failed: {}", exc)


def _format_admin_message(overall_status: str, alerts: list[dict]) -> str:
    """HTML-сообщение для админа: emoji + alertname + severity + краткое описание."""
    emoji = "🔥" if overall_status == "firing" else "✅"
    lines = [f"<b>{emoji} Alertmanager: {html.escape(overall_status)}</b>"]
    for alert in alerts:
        labels = alert.get("labels", {}) or {}
        annotations = alert.get("annotations", {}) or {}
        name = html.escape(str(labels.get("alertname", "?")))
        severity = html.escape(str(labels.get("severity", "?")))
        summary = html.escape(str(annotations.get("summary") or annotations.get("description", "")))
        state = html.escape(str(alert.get("status", "?")))
        lines.append(f"• [{state}] <b>{name}</b> ({severity}): {summary}")
    return "\n".join(lines)
