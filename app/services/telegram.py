"""Обёртка над Telegram Bot API для отправки уведомлений."""

import httpx
from loguru import logger

from app.config import settings


class TelegramNotConfiguredError(RuntimeError):
    """Бросается, если TELEGRAM_BOT_TOKEN не задан в настройках."""


class TelegramSendError(Exception):
    """Бросается на любую ошибку доставки сообщения (сетевая или 4xx/5xx)."""


_REQUEST_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


async def send_message(chat_id: str, text: str, parse_mode: str = "HTML") -> dict:
    """Отправить текстовое сообщение в Telegram-чат.

    Args:
        chat_id: целевой чат (строка с целым числом, может быть отрицательной для групп).
        text: текст сообщения. Длина в Telegram до 4096 символов.
        parse_mode: "HTML" | "MarkdownV2" | "" — формат разметки.

    Returns:
        dict с полем "result" из ответа Telegram API.

    Raises:
        TelegramNotConfiguredError: токен бота не сконфигурирован.
        TelegramSendError: Telegram вернул ошибку или сетевой сбой.
    """
    if not settings.telegram_bot_token:
        raise TelegramNotConfiguredError("TELEGRAM_BOT_TOKEN не задан в настройках")

    url = f"{settings.telegram_api_url}/bot{settings.telegram_bot_token}/sendMessage"
    payload: dict = {"chat_id": chat_id, "text": text}
    if parse_mode:
        payload["parse_mode"] = parse_mode

    try:
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
            response = await client.post(url, json=payload)
    except httpx.HTTPError as exc:
        logger.warning("Telegram send error to chat_id={}: {}", chat_id, exc)
        raise TelegramSendError(f"Сетевая ошибка при отправке в Telegram: {exc}") from exc

    if response.status_code != 200:
        # Telegram возвращает {"ok": false, "description": "...", "error_code": N}
        body = _safe_json(response)
        description = body.get("description", response.text)
        logger.warning(
            "Telegram API error: status={} chat_id={} description={}",
            response.status_code,
            chat_id,
            description,
        )
        raise TelegramSendError(f"Telegram вернул {response.status_code}: {description}")

    return response.json()


def _safe_json(response: httpx.Response) -> dict:
    """Распарсить тело ответа в dict, либо вернуть пустой dict при невалидном JSON."""
    try:
        data = response.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}
