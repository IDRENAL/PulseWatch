"""Тесты email-уведомлений: эндпоинт переключателя, сервис send_email, Celery-задача."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import aiosmtplib
import pytest
from httpx import AsyncClient

from app.services.email_alert import (
    EmailNotConfiguredError,
    EmailSendError,
    send_email,
)

# ─── PATCH /auth/me/email-alerts ────────────────────────────────────────────


async def test_toggle_email_alerts_disable(client: AsyncClient, auth_headers: dict[str, str]):
    response = await client.patch(
        "/auth/me/email-alerts", json={"enabled": False}, headers=auth_headers
    )
    assert response.status_code == 200
    assert response.json()["email_alerts_enabled"] is False


async def test_toggle_email_alerts_re_enable(client: AsyncClient, auth_headers: dict[str, str]):
    await client.patch("/auth/me/email-alerts", json={"enabled": False}, headers=auth_headers)
    response = await client.patch(
        "/auth/me/email-alerts", json={"enabled": True}, headers=auth_headers
    )
    assert response.json()["email_alerts_enabled"] is True


async def test_toggle_email_alerts_without_auth_returns_401(client: AsyncClient):
    response = await client.patch("/auth/me/email-alerts", json={"enabled": False})
    assert response.status_code == 401


async def test_user_read_includes_email_alerts_enabled(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """GET /auth/me возвращает поле email_alerts_enabled (default True)."""
    response = await client.get("/auth/me", headers=auth_headers)
    assert response.json()["email_alerts_enabled"] is True


# ─── send_email service ─────────────────────────────────────────────────────


async def test_send_email_raises_when_smtp_not_configured():
    with patch("app.services.email_alert.settings.smtp_host", None):
        with pytest.raises(EmailNotConfiguredError):
            await send_email("to@test.com", "subj", "<p>hi</p>", "hi")


async def test_send_email_raises_when_no_from_address():
    """Если ни SMTP_FROM_ADDRESS, ни SMTP_USER не заданы — нечем подписать."""
    with (
        patch("app.services.email_alert.settings.smtp_host", "smtp.example.com"),
        patch("app.services.email_alert.settings.smtp_from_address", None),
        patch("app.services.email_alert.settings.smtp_user", None),
    ):
        with pytest.raises(EmailNotConfiguredError, match="подписать"):
            await send_email("to@test.com", "subj", "<p>hi</p>", "hi")


async def test_send_email_calls_aiosmtplib_with_correct_args():
    with (
        patch("app.services.email_alert.settings.smtp_host", "smtp.example.com"),
        patch("app.services.email_alert.settings.smtp_port", 587),
        patch("app.services.email_alert.settings.smtp_user", "user@x"),
        patch("app.services.email_alert.settings.smtp_password", "pwd"),
        patch("app.services.email_alert.settings.smtp_from_address", "alerts@x"),
        patch("app.services.email_alert.settings.smtp_use_tls", True),
        patch("aiosmtplib.send", new=AsyncMock()) as send_mock,
    ):
        await send_email("to@test.com", "subj", "<p>hi</p>", "hi text")

    send_mock.assert_awaited_once()
    msg = send_mock.call_args[0][0]
    assert msg["From"] == "alerts@x"
    assert msg["To"] == "to@test.com"
    assert msg["Subject"] == "subj"
    kwargs = send_mock.call_args.kwargs
    assert kwargs["hostname"] == "smtp.example.com"
    assert kwargs["port"] == 587
    assert kwargs["username"] == "user@x"
    assert kwargs["password"] == "pwd"
    assert kwargs["start_tls"] is True


async def test_send_email_raises_on_smtp_error():
    with (
        patch("app.services.email_alert.settings.smtp_host", "smtp.example.com"),
        patch("app.services.email_alert.settings.smtp_from_address", "alerts@x"),
        patch(
            "aiosmtplib.send",
            new=AsyncMock(side_effect=aiosmtplib.SMTPException("relay denied")),
        ),
    ):
        with pytest.raises(EmailSendError, match="SMTP error"):
            await send_email("to@test.com", "subj", "<p>hi</p>", "hi")


async def test_send_email_raises_on_network_error():
    with (
        patch("app.services.email_alert.settings.smtp_host", "smtp.example.com"),
        patch("app.services.email_alert.settings.smtp_from_address", "alerts@x"),
        patch("aiosmtplib.send", new=AsyncMock(side_effect=OSError("timeout"))),
    ):
        with pytest.raises(EmailSendError, match="Сетевая"):
            await send_email("to@test.com", "subj", "<p>hi</p>", "hi")


# ─── send_email_alert Celery task ──────────────────────────────────────────


def _make_event_row(*, email_alerts_enabled: bool = True):
    event = MagicMock(metric_value=95.0, threshold_value=90.0, created_at=datetime.now(UTC))
    rule = MagicMock(metric_field="cpu_percent")
    rule.name = "cpu high"
    rule.operator.value = "gt"
    server = MagicMock(id=42)
    server.name = "prod-1"
    user = MagicMock(id=1, email="alice@test.com", email_alerts_enabled=email_alerts_enabled)
    return event, rule, server, user


def _patched_session_with(row):
    cm = AsyncMock()
    sess = AsyncMock()
    sess.execute.return_value.first = MagicMock(return_value=row)
    cm.__aenter__.return_value = sess
    return cm


def _fake_redis():
    fake = AsyncMock()
    fake.aclose = AsyncMock()
    return fake


def test_send_email_alert_skips_when_event_missing():
    from app.tasks.notification_tasks import send_email_alert

    cm = _patched_session_with(None)
    with (
        patch("app.database.async_session_factory", return_value=cm),
        patch("app.tasks.notification_tasks.Redis.from_url", return_value=_fake_redis()),
        patch("app.tasks.notification_tasks.send_email", new=AsyncMock()) as send_mock,
    ):
        send_email_alert(event_id=99999)
    send_mock.assert_not_called()


def test_send_email_alert_skips_when_user_disabled_email():
    from app.tasks.notification_tasks import send_email_alert

    row = _make_event_row(email_alerts_enabled=False)
    cm = _patched_session_with(row)
    with (
        patch("app.database.async_session_factory", return_value=cm),
        patch("app.tasks.notification_tasks.Redis.from_url", return_value=_fake_redis()),
        patch("app.tasks.notification_tasks.is_channel_muted", new=AsyncMock(return_value=False)),
        patch("app.tasks.notification_tasks.send_email", new=AsyncMock()) as send_mock,
    ):
        send_email_alert(event_id=1)
    send_mock.assert_not_called()


def test_send_email_alert_skips_when_server_muted():
    from app.tasks.notification_tasks import send_email_alert

    row = _make_event_row()
    cm = _patched_session_with(row)
    with (
        patch("app.database.async_session_factory", return_value=cm),
        patch("app.tasks.notification_tasks.Redis.from_url", return_value=_fake_redis()),
        patch("app.tasks.notification_tasks.is_channel_muted", new=AsyncMock(return_value=True)),
        patch("app.tasks.notification_tasks.send_email", new=AsyncMock()) as send_mock,
    ):
        send_email_alert(event_id=1)
    send_mock.assert_not_called()


def test_send_email_alert_happy_path_uses_user_email():
    from app.tasks.notification_tasks import send_email_alert

    row = _make_event_row()
    cm = _patched_session_with(row)
    with (
        patch("app.database.async_session_factory", return_value=cm),
        patch("app.tasks.notification_tasks.Redis.from_url", return_value=_fake_redis()),
        patch("app.tasks.notification_tasks.is_channel_muted", new=AsyncMock(return_value=False)),
        patch("app.tasks.notification_tasks.send_email", new=AsyncMock()) as send_mock,
    ):
        send_email_alert(event_id=1)
    send_mock.assert_called_once()
    args = send_mock.call_args[0]
    assert args[0] == "alice@test.com"  # to
    assert "cpu high" in args[1]  # subject
    assert "prod-1" in args[2] or "prod-1" in args[3]  # html or text body


def test_send_email_alert_skips_when_smtp_not_configured():
    """EmailNotConfiguredError → лог + return, без ретрая."""
    from app.services.email_alert import EmailNotConfiguredError
    from app.tasks.notification_tasks import send_email_alert

    row = _make_event_row()
    cm = _patched_session_with(row)
    with (
        patch("app.database.async_session_factory", return_value=cm),
        patch("app.tasks.notification_tasks.Redis.from_url", return_value=_fake_redis()),
        patch("app.tasks.notification_tasks.is_channel_muted", new=AsyncMock(return_value=False)),
        patch(
            "app.tasks.notification_tasks.send_email",
            new=AsyncMock(side_effect=EmailNotConfiguredError("not set")),
        ),
    ):
        # Не должно бросить — Celery не будет ретраить
        send_email_alert(event_id=1)
