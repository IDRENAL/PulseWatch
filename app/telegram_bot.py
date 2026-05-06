"""Telegram-бот для привязки чата к юзеру через `/start <код>`.

Запускается как отдельный процесс (`python -m app.telegram_bot`).
Использует long-polling: GET /getUpdates с offset, висим до 30с в ожидании.
Хендлер у нас один — `/start <code>` — больше команд не поддерживается.
"""

import asyncio
import re

import httpx
from loguru import logger
from redis.asyncio import Redis
from sqlalchemy import update

from app.config import settings
from app.database import async_session_factory
from app.models.user import User
from app.redis_client import consume_tg_link_code, set_redis_client

_POLL_TIMEOUT_SECONDS = 30
_HTTP_TIMEOUT = httpx.Timeout(_POLL_TIMEOUT_SECONDS + 10, connect=10.0)
_START_PATTERN = re.compile(r"^/start\s+(?P<code>\S+)\s*$")


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


async def _handle_message(client: httpx.AsyncClient, message: dict) -> None:
    """Обрабатывает одно входящее сообщение. /start <code> — привязка, остальное игнор."""
    chat_id = message.get("chat", {}).get("id")
    text = message.get("text", "")

    match = _START_PATTERN.match(text)
    if not match:
        # Не /start <code> — отвечаем подсказкой
        if chat_id and text.startswith("/start"):
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
        await _send(client, chat_id, "✅ Аккаунт привязан. Теперь алерты будут приходить сюда.")
    else:
        await _send(client, chat_id, "❌ Юзер не найден. Возможно, аккаунт удалён.")


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
