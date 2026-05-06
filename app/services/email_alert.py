"""Обёртка над SMTP для отправки уведомлений об алертах."""

from email.message import EmailMessage

import aiosmtplib
from loguru import logger

from app.config import settings


class EmailNotConfiguredError(RuntimeError):
    """Бросается, если SMTP_HOST не задан в настройках."""


class EmailSendError(Exception):
    """Бросается на любую ошибку доставки (сетевая, SMTP-ответ 4xx/5xx)."""


_TIMEOUT_SECONDS = 30.0


async def send_email(to: str, subject: str, html_body: str, text_body: str) -> None:
    """Отправить multipart email (HTML + plain-text fallback) через SMTP.

    Raises:
        EmailNotConfiguredError: SMTP_HOST не сконфигурирован.
        EmailSendError: на любую ошибку доставки.
    """
    if not settings.smtp_host:
        raise EmailNotConfiguredError("SMTP_HOST не задан в настройках")

    from_addr = settings.smtp_from_address or settings.smtp_user
    if not from_addr:
        raise EmailNotConfiguredError(
            "Не задан SMTP_FROM_ADDRESS и нет SMTP_USER — некому подписать письмо"
        )

    msg = EmailMessage()
    msg["From"] = from_addr
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text_body)
    msg.add_alternative(html_body, subtype="html")

    try:
        await aiosmtplib.send(
            msg,
            hostname=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_user,
            password=settings.smtp_password,
            start_tls=settings.smtp_use_tls,
            timeout=_TIMEOUT_SECONDS,
        )
    except aiosmtplib.SMTPException as exc:
        logger.warning("SMTP error to {}: {}", to, exc)
        raise EmailSendError(f"SMTP error: {exc}") from exc
    except OSError as exc:
        # Сетевые ошибки (timeout, connection refused и т.п.) — поднимаются как OSError
        logger.warning("Network error to {}: {}", to, exc)
        raise EmailSendError(f"Сетевая ошибка SMTP: {exc}") from exc
