"""Задачи отправки уведомлений (Telegram, email)."""

import asyncio
import html

from loguru import logger
from redis.asyncio import Redis
from sqlalchemy import select

from app.config import settings
from app.core.observability import notifications_sent_total
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
            notifications_sent_total.labels(channel="telegram", status="skipped").inc()
            return

        if await is_channel_muted(server.id, "telegram"):
            logger.info(
                "send_telegram_alert: server id={} telegram-muted, skipping event id={}",
                server.id,
                event_id,
            )
            notifications_sent_total.labels(channel="telegram", status="skipped").inc()
            return

        text = _format_message(event, rule, server)

        try:
            await send_message(user.telegram_chat_id, text)
            notifications_sent_total.labels(channel="telegram", status="success").inc()
        except TelegramNotConfiguredError:
            logger.warning(
                "send_telegram_alert: TELEGRAM_BOT_TOKEN не задан, пропускаем event id={}",
                event_id,
            )
            notifications_sent_total.labels(channel="telegram", status="skipped").inc()
            return
        except TelegramSendError:
            notifications_sent_total.labels(channel="telegram", status="failed").inc()
            raise
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
            notifications_sent_total.labels(channel="email", status="skipped").inc()
            return

        if await is_channel_muted(server.id, "email"):
            logger.info(
                "send_email_alert: server id={} email-muted, skipping event id={}",
                server.id,
                event_id,
            )
            notifications_sent_total.labels(channel="email", status="skipped").inc()
            return

        subject = f"[PulseWatch] {rule.name} — {server.name}"
        html_body = _format_message(event, rule, server).replace("\n", "<br>")
        text_body = _format_text(event, rule, server)

        try:
            await send_email(user.email, subject, html_body, text_body)
            notifications_sent_total.labels(channel="email", status="success").inc()
        except EmailNotConfiguredError:
            logger.warning(
                "send_email_alert: SMTP не сконфигурирован, пропускаем event id={}",
                event_id,
            )
            notifications_sent_total.labels(channel="email", status="skipped").inc()
            return
        except EmailSendError:
            notifications_sent_total.labels(channel="email", status="failed").inc()
            raise
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


# ─── Heartbeat-уведомления (server down / recovered) ────────────────────────


@celery_app.task(name="app.tasks.notification_tasks.send_heartbeat_down")
def send_heartbeat_down(server_id: int) -> None:
    """Шлёт владельцу сервера сообщение о том, что сервер замолчал."""
    asyncio.run(_send_heartbeat(server_id, recovered=False))


@celery_app.task(name="app.tasks.notification_tasks.send_heartbeat_recovery")
def send_heartbeat_recovery(server_id: int) -> None:
    """Шлёт владельцу сервера сообщение о том, что сервер снова в строю."""
    asyncio.run(_send_heartbeat(server_id, recovered=True))


async def _send_heartbeat(server_id: int, recovered: bool) -> None:
    from app.database import async_session_factory

    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    set_redis_client(redis)
    try:
        async with async_session_factory() as db:
            stmt = (
                select(Server, User)
                .join(User, Server.owner_id == User.id)
                .where(Server.id == server_id)
            )
            row = (await db.execute(stmt)).first()

        if row is None:
            logger.warning("heartbeat notify: server id={} not found", server_id)
            return
        server, user = row

        emoji, status_text = ("✅", "снова в строю") if recovered else ("⚠️", "не отвечает")
        last_seen = server.last_seen_at.isoformat() if server.last_seen_at else "ни разу"

        # Telegram — если привязан chat_id и сервер не в mute'е
        if user.telegram_chat_id and not await is_channel_muted(server.id, "telegram"):
            tg_text = (
                f"{emoji} <b>Сервер {html.escape(server.name)} {status_text}</b>\n"
                f"id: <code>{server.id}</code>\n"
                f"last seen: {html.escape(last_seen)}"
            )
            try:
                await send_message(user.telegram_chat_id, tg_text)
            except (TelegramNotConfiguredError, TelegramSendError) as exc:
                logger.info("heartbeat tg send skipped: {}", exc)

        # Email — если включены email-уведомления и не в mute'е
        if user.email_alerts_enabled and not await is_channel_muted(server.id, "email"):
            subject = f"[PulseWatch] {server.name} {status_text}"
            html_body = (
                f"<p>{emoji} <b>{html.escape(server.name)}</b> {status_text}.</p>"
                f"<p>last seen: {html.escape(last_seen)}</p>"
            )
            text_body = f"{emoji} {server.name} {status_text}. last seen: {last_seen}"
            try:
                await send_email(user.email, subject, html_body, text_body)
            except (EmailNotConfiguredError, EmailSendError) as exc:
                logger.info("heartbeat email send skipped: {}", exc)
    finally:
        await redis.aclose()
        set_redis_client(None)
