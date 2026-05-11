"""Задачи отправки уведомлений (Telegram, email)."""

import asyncio
import html

from loguru import logger
from redis.asyncio import Redis
from sqlalchemy import select

from app.config import settings
from app.models.alert_event import AlertEvent
from app.models.alert_rule import AlertRule
from app.models.server import Server
from app.models.user import User
from app.redis_client import is_channel_muted, set_redis_client
from app.services.email_alert import (
    EmailNotConfiguredError,
    EmailSendError,
    send_email,
)
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

    # Celery-воркер не запускает FastAPI lifespan, поэтому Redis-клиент
    # надо инициализировать локально для проверки mute.
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    set_redis_client(redis)
    try:
        async with async_session_factory() as db:
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

        if await is_channel_muted(server.id, "telegram"):
            logger.info(
                "send_telegram_alert: server id={} telegram-muted, skipping event id={}",
                server.id,
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
    finally:
        await redis.aclose()
        set_redis_client(None)


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


# ─── Email-уведомления ──────────────────────────────────────────────────────


@celery_app.task(
    name="app.tasks.notification_tasks.send_email_alert",
    autoretry_for=(EmailSendError,),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=5,
)
def send_email_alert(event_id: int) -> None:
    """Отправляет email об алерте. Логика как у telegram-алерта:
    EmailSendError → Celery ретраит, остальное — log + return.
    """
    asyncio.run(_send_email(event_id))


async def _send_email(event_id: int) -> None:
    from app.database import async_session_factory

    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    set_redis_client(redis)
    try:
        async with async_session_factory() as db:
            stmt = (
                select(AlertEvent, AlertRule, Server, User)
                .join(AlertRule, AlertEvent.rule_id == AlertRule.id)
                .join(Server, AlertEvent.server_id == Server.id)
                .join(User, Server.owner_id == User.id)
                .where(AlertEvent.id == event_id)
            )
            row = (await db.execute(stmt)).first()

        if row is None:
            logger.warning("send_email_alert: AlertEvent id={} not found", event_id)
            return

        event, rule, server, user = row

        if not user.email_alerts_enabled:
            logger.info(
                "send_email_alert: user id={} disabled email alerts, skipping event id={}",
                user.id,
                event_id,
            )
            return

        if await is_channel_muted(server.id, "email"):
            logger.info(
                "send_email_alert: server id={} email-muted, skipping event id={}",
                server.id,
                event_id,
            )
            return

        subject = f"[PulseWatch] {rule.name} — {server.name}"
        html_body = _format_message(event, rule, server).replace("\n", "<br>")
        text_body = _format_text(event, rule, server)

        try:
            await send_email(user.email, subject, html_body, text_body)
        except EmailNotConfiguredError:
            logger.warning(
                "send_email_alert: SMTP не сконфигурирован, пропускаем event id={}",
                event_id,
            )
            return
        # EmailSendError пробрасывается выше — Celery сделает ретрай
    finally:
        await redis.aclose()
        set_redis_client(None)


def _format_text(event: AlertEvent, rule: AlertRule, server: Server) -> str:
    """Plain-text fallback для почтовых клиентов без HTML."""
    return (
        f"PulseWatch alert: {rule.name}\n"
        f"Server: {server.name}\n"
        f"Metric: {rule.metric_field} = {event.metric_value}\n"
        f"Threshold: {rule.operator.value} {event.threshold_value}\n"
        f"Time: {event.created_at.isoformat()}\n"
    )
