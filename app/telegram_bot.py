"""Telegram-бот: привязка аккаунта через `/start <код>` + команды для
привязанных юзеров: `/status`, `/servers`, `/mute <server_id> <minutes>`.

Запускается как отдельный процесс (`python -m app.telegram_bot`).
Long-polling: GET /getUpdates с offset.
"""

import asyncio
import re

import httpx
from loguru import logger
from redis.asyncio import Redis
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import async_session_factory
from app.models.alert_event import AlertEvent
from app.models.metric import Metric
from app.models.server import Server
from app.models.user import User
from app.redis_client import (
    consume_tg_link_code,
    get_mute_ttl,
    set_redis_client,
    set_server_mute,
)

_POLL_TIMEOUT_SECONDS = 30
_HTTP_TIMEOUT = httpx.Timeout(_POLL_TIMEOUT_SECONDS + 10, connect=10.0)
_START_PATTERN = re.compile(r"^/start\s+(?P<code>\S+)\s*$")
_MUTE_PATTERN = re.compile(r"^/mute\s+(?P<server_id>\d+)\s+(?P<minutes>\d+)\s*$")


def _bot_url(method: str) -> str:
    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN не задан")
    return f"{settings.telegram_api_url}/bot{settings.telegram_bot_token}/{method}"


async def _send(client: httpx.AsyncClient, chat_id: int | str, text: str) -> None:
    """Best-effort отправка ответа. Ошибки логируем, но не валим polling."""
    try:
        await client.post(_bot_url("sendMessage"), json={"chat_id": chat_id, "text": text})
    except httpx.HTTPError as exc:
        logger.warning("send to chat_id={} failed: {}", chat_id, exc)


async def _link_user(user_id: int, chat_id: int) -> bool:
    """Записывает chat_id в users.telegram_chat_id. True если юзер найден."""
    async with async_session_factory() as db:
        result = await db.execute(
            update(User)
            .where(User.id == user_id)
            .values(telegram_chat_id=str(chat_id))
            .returning(User.id)
        )
        await db.commit()
        return result.scalar_one_or_none() is not None


async def _find_user_by_chat_id(db: AsyncSession, chat_id: int) -> User | None:
    """Ищет юзера по привязанному chat_id."""
    result = await db.execute(select(User).where(User.telegram_chat_id == str(chat_id)))
    return result.scalar_one_or_none()


# ─── Команда /start <code> — привязка ───────────────────────────────────────


async def _handle_start(client: httpx.AsyncClient, chat_id: int, text: str) -> None:
    match = _START_PATTERN.match(text)
    if not match:
        await _send(
            client,
            chat_id,
            "Привет! Чтобы привязать этот чат к аккаунту PulseWatch, "
            "получи одноразовый код через POST /auth/me/telegram/code "
            "и отправь мне `/start <код>`.",
        )
        return

    code = match.group("code")
    user_id = await consume_tg_link_code(code)
    if user_id is None:
        await _send(client, chat_id, "❌ Код истёк или неверен. Запроси новый.")
        return

    linked = await _link_user(user_id, chat_id)
    if linked:
        await _send(
            client,
            chat_id,
            "✅ Аккаунт привязан. Теперь алерты будут приходить сюда.\n"
            "Команды: /status, /servers, /mute <server_id> <minutes>",
        )
    else:
        await _send(client, chat_id, "❌ Юзер не найден. Возможно, аккаунт удалён.")


# ─── Команда /status — сводка ───────────────────────────────────────────────


async def _handle_status(client: httpx.AsyncClient, chat_id: int, user: User) -> None:
    async with async_session_factory() as db:
        servers = (
            (await db.execute(select(Server).where(Server.owner_id == user.id))).scalars().all()
        )
        if not servers:
            await _send(client, chat_id, "У тебя нет зарегистрированных серверов.")
            return

        lines = [f"📊 Серверы ({len(servers)}):"]
        for server in servers:
            latest = (
                await db.execute(
                    select(Metric)
                    .where(Metric.server_id == server.id)
                    .order_by(Metric.collected_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()

            open_events = (
                await db.execute(
                    select(AlertEvent.id).where(
                        AlertEvent.server_id == server.id,
                        AlertEvent.resolved_at.is_(None),
                    )
                )
            ).all()

            metric_part = (
                f"cpu={latest.cpu_percent:.1f}% mem={latest.memory_percent:.1f}% "
                f"disk={latest.disk_percent:.1f}%"
                if latest
                else "нет данных"
            )
            mute_ttl = await get_mute_ttl(server.id)
            mute_part = f" 🔇{mute_ttl // 60}m" if mute_ttl else ""
            alert_part = f" 🚨{len(open_events)}" if open_events else ""
            lines.append(f"• #{server.id} {server.name}: {metric_part}{alert_part}{mute_part}")

    await _send(client, chat_id, "\n".join(lines))


# ─── Команда /servers — подробный список ─────────────────────────────────────


async def _handle_servers(client: httpx.AsyncClient, chat_id: int, user: User) -> None:
    async with async_session_factory() as db:
        servers = (
            (await db.execute(select(Server).where(Server.owner_id == user.id))).scalars().all()
        )

    if not servers:
        await _send(client, chat_id, "У тебя нет зарегистрированных серверов.")
        return

    lines = [f"🖥 Серверы ({len(servers)}):"]
    for server in servers:
        seen = server.last_seen_at.isoformat() if server.last_seen_at else "ни разу"
        active = "✅" if server.is_active else "⏸"
        lines.append(f"• #{server.id} {server.name} {active} last_seen={seen}")
    await _send(client, chat_id, "\n".join(lines))


# ─── Команда /mute <server_id> <minutes> ─────────────────────────────────────


async def _handle_mute(client: httpx.AsyncClient, chat_id: int, user: User, text: str) -> None:
    match = _MUTE_PATTERN.match(text)
    if not match:
        await _send(client, chat_id, "Использование: /mute <server_id> <minutes>")
        return

    server_id = int(match.group("server_id"))
    minutes = int(match.group("minutes"))

    if minutes <= 0 or minutes > 1440:
        await _send(client, chat_id, "❌ minutes должен быть в диапазоне 1..1440")
        return

    async with async_session_factory() as db:
        server = (
            await db.execute(
                select(Server).where(Server.id == server_id, Server.owner_id == user.id)
            )
        ).scalar_one_or_none()

    if server is None:
        await _send(client, chat_id, "❌ Сервер не найден или не твой.")
        return

    await set_server_mute(server_id, minutes)
    await _send(client, chat_id, f"🔇 Сервер #{server_id} {server.name} заглушен на {minutes} мин.")


# ─── Главный диспетчер ──────────────────────────────────────────────────────


async def _handle_message(client: httpx.AsyncClient, message: dict) -> None:
    """Обрабатывает одно входящее сообщение."""
    chat_id = message.get("chat", {}).get("id")
    text = message.get("text", "")
    if not chat_id or not text:
        return

    # /start не требует привязки — он её и делает
    if text.startswith("/start"):
        await _handle_start(client, chat_id, text)
        return

    # Все остальные команды требуют привязанного юзера
    if not text.startswith("/"):
        return  # игнорируем обычный текст

    async with async_session_factory() as db:
        user = await _find_user_by_chat_id(db, chat_id)
    if user is None:
        await _send(
            client,
            chat_id,
            "Этот чат не привязан к аккаунту. Получи код через "
            "POST /auth/me/telegram/code и отправь /start <код>.",
        )
        return

    if text.startswith("/status"):
        await _handle_status(client, chat_id, user)
    elif text.startswith("/servers"):
        await _handle_servers(client, chat_id, user)
    elif text.startswith("/mute"):
        await _handle_mute(client, chat_id, user, text)
    else:
        await _send(
            client,
            chat_id,
            "Неизвестная команда. Доступные: /status, /servers, /mute <server_id> <minutes>",
        )


async def _poll_loop() -> None:
    """Основной цикл: long-polling getUpdates с offset, обработка по одной message."""
    offset: int | None = None

    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        while True:
            params: dict = {"timeout": _POLL_TIMEOUT_SECONDS, "allowed_updates": ["message"]}
            if offset is not None:
                params["offset"] = offset

            try:
                response = await client.get(_bot_url("getUpdates"), params=params)
            except httpx.HTTPError as exc:
                logger.warning("getUpdates failed: {}; retry in 5s", exc)
                await asyncio.sleep(5)
                continue

            if response.status_code != 200:
                logger.warning("getUpdates non-200: {} {}", response.status_code, response.text)
                await asyncio.sleep(5)
                continue

            data = response.json()
            for update_obj in data.get("result", []):
                offset = update_obj["update_id"] + 1
                message = update_obj.get("message")
                if message:
                    try:
                        await _handle_message(client, message)
                    except Exception as exc:
                        logger.exception("handler error for update {}: {}", update_obj, exc)


async def run_bot() -> None:
    """Точка входа: подключаемся к Redis, стартуем polling-цикл."""
    if not settings.telegram_bot_token:
        logger.error("TELEGRAM_BOT_TOKEN не задан — бот не будет запущен")
        return

    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    set_redis_client(redis)
    logger.info("Telegram-бот стартует, polling timeout={}s", _POLL_TIMEOUT_SECONDS)
    try:
        await _poll_loop()
    finally:
        await redis.aclose()
        set_redis_client(None)


if __name__ == "__main__":
    asyncio.run(run_bot())
