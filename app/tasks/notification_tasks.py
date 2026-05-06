"""Задачи отправки уведомлений (Telegram)."""

import asyncio
import html

from loguru import logger
from sqlalchemy import select

from app.models.alert_event import AlertEvent
from app.models.alert_rule import AlertRule
from app.models.server import Server
from app.models.user import User
from app.services.telegram import (
    TelegramNotConfiguredError,
    TelegramSendError,
    send_message,
)
from app.tasks.celery_app import celery_app


@celery_app.task(
    name="app.tasks.notification_tasks.send_telegram_alert",
    autoretry_for=(TelegramSendError,),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=5,
)
def send_telegram_alert(event_id: int) -> None:
    """Отправляет владельцу сервера уведомление об алерте в Telegram.

    На TelegramSendError Celery сам повторит задачу с экспоненциальным backoff.
    На остальные ошибки (нет юзера, нет привязки, нет токена) — лог и выход.
    """
    asyncio.run(_send(event_id))


async def _send(event_id: int) -> None:
    from app.database import async_session_factory

    async with async_session_factory() as db:
        # Подтягиваем event + rule + server + user одним запросом
        stmt = (
            select(AlertEvent, AlertRule, Server, User)
            .join(AlertRule, AlertEvent.rule_id == AlertRule.id)
            .join(Server, AlertEvent.server_id == Server.id)
            .join(User, Server.owner_id == User.id)
            .where(AlertEvent.id == event_id)
        )
        row = (await db.execute(stmt)).first()

    if row is None:
        logger.warning("send_telegram_alert: AlertEvent id={} not found", event_id)
        return

    event, rule, server, user = row

    if not user.telegram_chat_id:
        logger.info(
            "send_telegram_alert: user id={} has no telegram_chat_id, skipping event id={}",
            user.id,
            event_id,
        )
        return

    text = _format_message(event, rule, server)

    try:
        await send_message(user.telegram_chat_id, text)
    except TelegramNotConfiguredError:
        logger.warning(
            "send_telegram_alert: TELEGRAM_BOT_TOKEN не задан, пропускаем event id={}",
            event_id,
        )
        return
    # TelegramSendError пробрасывается выше — Celery сделает ретрай


def _format_message(event: AlertEvent, rule: AlertRule, server: Server) -> str:
    """Формирует HTML-сообщение об алерте."""
    return (
        f"<b>🚨 Алерт: {html.escape(rule.name)}</b>\n"
        f"Сервер: <code>{html.escape(server.name)}</code>\n"
        f"Метрика: <code>{html.escape(rule.metric_field)}</code> "
        f"= <b>{event.metric_value}</b>\n"
        f"Порог: <code>{rule.operator.value}</code> {event.threshold_value}\n"
        f"Время: {event.created_at.isoformat()}"
    )
