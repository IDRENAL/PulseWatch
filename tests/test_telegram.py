"""Тесты Telegram-уведомлений: схема, эндпоинт привязки, сервис, Celery-задача."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from httpx import AsyncClient
from pydantic import ValidationError

from app.schemas.user import TelegramLink
from app.services.telegram import (
    TelegramNotConfiguredError,
    TelegramSendError,
    send_message,
)

# ─── TelegramLink schema validator ──────────────────────────────────────────


def test_telegram_link_accepts_positive_int_string():
    assert TelegramLink(chat_id="12345").chat_id == "12345"


def test_telegram_link_accepts_negative_int_string():
    assert TelegramLink(chat_id="-100123").chat_id == "-100123"


def test_telegram_link_accepts_none():
    assert TelegramLink(chat_id=None).chat_id is None


def test_telegram_link_strips_whitespace():
    assert TelegramLink(chat_id="  123  ").chat_id == "123"


@pytest.mark.parametrize("bad", ["abc", "", "   ", "-", "12.5", "1 2", "1a"])
def test_telegram_link_rejects_non_integer(bad):
    with pytest.raises(ValidationError):
        TelegramLink(chat_id=bad)


# ─── PATCH /auth/me/telegram endpoint ───────────────────────────────────────


async def test_patch_telegram_links_chat_id(client: AsyncClient, auth_headers: dict[str, str]):
    response = await client.patch(
        "/auth/me/telegram",
        json={"chat_id": "987654321"},
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert response.json()["telegram_chat_id"] == "987654321"

    # GET /auth/me возвращает то же значение
    me = await client.get("/auth/me", headers=auth_headers)
    assert me.json()["telegram_chat_id"] == "987654321"


async def test_patch_telegram_unlinks_with_null(client: AsyncClient, auth_headers: dict[str, str]):
    await client.patch(
        "/auth/me/telegram",
        json={"chat_id": "111"},
        headers=auth_headers,
    )
    response = await client.patch(
        "/auth/me/telegram",
        json={"chat_id": None},
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert response.json()["telegram_chat_id"] is None


async def test_patch_telegram_invalid_chat_id_returns_422(
    client: AsyncClient, auth_headers: dict[str, str]
):
    response = await client.patch(
        "/auth/me/telegram",
        json={"chat_id": "abc"},
        headers=auth_headers,
    )
    assert response.status_code == 422


async def test_patch_telegram_without_auth_returns_401(client: AsyncClient):
    response = await client.patch("/auth/me/telegram", json={"chat_id": "1"})
    assert response.status_code == 401


# ─── send_message service ───────────────────────────────────────────────────


async def test_send_message_raises_when_token_missing():
    with patch("app.services.telegram.settings.telegram_bot_token", None):
        with pytest.raises(TelegramNotConfiguredError):
            await send_message("123", "test")


async def test_send_message_returns_response_on_200():
    fake = MagicMock(spec=httpx.Response)
    fake.status_code = 200
    fake.json = MagicMock(return_value={"ok": True, "result": {"message_id": 42}})
    with (
        patch("app.services.telegram.settings.telegram_bot_token", "fake_token"),
        patch("httpx.AsyncClient.post", new=AsyncMock(return_value=fake)),
    ):
        result = await send_message("123", "hello")
    assert result == {"ok": True, "result": {"message_id": 42}}


async def test_send_message_raises_on_4xx():
    fake = MagicMock(spec=httpx.Response)
    fake.status_code = 400
    fake.json = MagicMock(return_value={"ok": False, "description": "chat not found"})
    fake.text = "..."
    with (
        patch("app.services.telegram.settings.telegram_bot_token", "fake_token"),
        patch("httpx.AsyncClient.post", new=AsyncMock(return_value=fake)),
    ):
        with pytest.raises(TelegramSendError, match="400"):
            await send_message("999", "hello")


async def test_send_message_raises_on_network_error():
    with (
        patch("app.services.telegram.settings.telegram_bot_token", "fake_token"),
        patch(
            "httpx.AsyncClient.post",
            new=AsyncMock(side_effect=httpx.ConnectError("refused")),
        ),
    ):
        with pytest.raises(TelegramSendError, match="Сетевая"):
            await send_message("123", "hello")


async def test_send_message_includes_html_parse_mode_in_payload():
    """Проверяем, что parse_mode по умолчанию = HTML и попадает в тело запроса."""
    fake = MagicMock(spec=httpx.Response)
    fake.status_code = 200
    fake.json = MagicMock(return_value={"ok": True})

    captured: dict = {}

    async def capture_post(self, url, json):  # noqa: A002
        captured["url"] = url
        captured["json"] = json
        return fake

    with (
        patch("app.services.telegram.settings.telegram_bot_token", "fake_token"),
        patch("httpx.AsyncClient.post", new=capture_post),
    ):
        await send_message("123", "hi")

    assert "/bot fake_token/sendMessage".replace(" ", "") in captured["url"].replace(" ", "")
    assert captured["json"]["chat_id"] == "123"
    assert captured["json"]["text"] == "hi"
    assert captured["json"]["parse_mode"] == "HTML"


# ─── send_telegram_alert Celery task ─────────────────────────────────────────


def test_send_telegram_alert_skips_when_event_missing():
    """Не падает и не зовёт send_message, если AlertEvent в БД нет."""
    from app.tasks.notification_tasks import send_telegram_alert

    fake_session_cm = AsyncMock()
    fake_session = AsyncMock()
    fake_session.execute.return_value.first = MagicMock(return_value=None)
    fake_session_cm.__aenter__.return_value = fake_session

    with (
        patch("app.database.async_session_factory", return_value=fake_session_cm),
        patch("app.services.telegram.send_message", new=AsyncMock()) as send_mock,
    ):
        send_telegram_alert(event_id=99999)

    send_mock.assert_not_called()


def test_send_telegram_alert_skips_when_user_has_no_chat_id():
    """Не зовёт send_message, если у юзера telegram_chat_id=None."""
    from app.tasks.notification_tasks import send_telegram_alert

    event = MagicMock(metric_value=95.0, threshold_value=90.0, created_at=datetime.now(UTC))
    rule = MagicMock(name="cpu high", metric_field="cpu_percent")
    rule.operator.value = "gt"
    server = MagicMock(name="prod-1")
    user = MagicMock(id=1, telegram_chat_id=None)

    fake_session_cm = AsyncMock()
    fake_session = AsyncMock()
    fake_session.execute.return_value.first = MagicMock(return_value=(event, rule, server, user))
    fake_session_cm.__aenter__.return_value = fake_session

    with (
        patch("app.database.async_session_factory", return_value=fake_session_cm),
        patch("app.tasks.notification_tasks.send_message", new=AsyncMock()) as send_mock,
    ):
        send_telegram_alert(event_id=1)

    send_mock.assert_not_called()


def test_send_telegram_alert_calls_send_message_with_html():
    """Happy path: формируется HTML-текст и шлётся юзеру."""
    from app.tasks.notification_tasks import send_telegram_alert

    event = MagicMock(metric_value=95.0, threshold_value=90.0, created_at=datetime.now(UTC))
    rule = MagicMock(metric_field="cpu_percent")
    rule.name = "high cpu"
    rule.operator.value = "gt"
    server = MagicMock()
    server.name = "prod-1"
    user = MagicMock(id=1, telegram_chat_id="555")

    fake_session_cm = AsyncMock()
    fake_session = AsyncMock()
    fake_session.execute.return_value.first = MagicMock(return_value=(event, rule, server, user))
    fake_session_cm.__aenter__.return_value = fake_session

    with (
        patch("app.database.async_session_factory", return_value=fake_session_cm),
        patch("app.tasks.notification_tasks.send_message", new=AsyncMock()) as send_mock,
    ):
        send_telegram_alert(event_id=1)

    send_mock.assert_called_once()
    args, _ = send_mock.call_args
    assert args[0] == "555"
    text = args[1]
    assert "high cpu" in text
    assert "prod-1" in text
    assert "cpu_percent" in text
    assert "<b>" in text  # HTML формат


# ─── threshold.py wiring ─────────────────────────────────────────────────────


# ─── POST /auth/me/telegram/code (link code generation) ─────────────────────


async def test_create_telegram_link_code_returns_code(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """Авторизованный юзер получает 8-символьный hex-код с TTL 600s."""
    with (
        patch("app.api.auth.settings.telegram_bot_username", "pulsewatch_test_bot"),
        patch("app.api.auth.store_tg_link_code", new=AsyncMock()) as store_mock,
    ):
        response = await client.post("/auth/me/telegram/code", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert len(body["code"]) == 8
    assert all(c in "0123456789abcdef" for c in body["code"])
    assert body["expires_in_seconds"] == 600
    assert body["deep_link"] == f"https://t.me/pulsewatch_test_bot?start={body['code']}"
    store_mock.assert_awaited_once()
    args, _ = store_mock.call_args
    assert args[0] == body["code"]  # код, который вернули = код, который сохранили


async def test_create_telegram_link_code_without_bot_username(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """Если TELEGRAM_BOT_USERNAME не задан — deep_link = None, код всё равно отдаётся."""
    with (
        patch("app.api.auth.settings.telegram_bot_username", None),
        patch("app.api.auth.store_tg_link_code", new=AsyncMock()),
    ):
        response = await client.post("/auth/me/telegram/code", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["code"]
    assert body["deep_link"] is None


async def test_create_telegram_link_code_without_auth_returns_401(client: AsyncClient):
    response = await client.post("/auth/me/telegram/code")
    assert response.status_code == 401


# ─── telegram_bot._handle_message ───────────────────────────────────────────


async def test_bot_handle_start_with_valid_code_links_user():
    """`/start <valid>` находит юзера, вызывает _link_user и шлёт success."""
    from app.telegram_bot import _handle_message

    client_mock = AsyncMock()
    message = {"chat": {"id": 555}, "text": "/start abc123"}

    with (
        patch("app.telegram_bot.consume_tg_link_code", new=AsyncMock(return_value=42)),
        patch("app.telegram_bot._link_user", new=AsyncMock(return_value=True)) as link_mock,
        patch("app.telegram_bot._send", new=AsyncMock()) as send_mock,
    ):
        await _handle_message(client_mock, message)

    link_mock.assert_awaited_once_with(42, 555)
    send_mock.assert_awaited_once()
    text = send_mock.call_args[0][2]
    assert "привязан" in text.lower()


async def test_bot_handle_start_with_expired_code():
    """`/start <expired>` → consume вернул None → шлём «код истёк»."""
    from app.telegram_bot import _handle_message

    client_mock = AsyncMock()
    message = {"chat": {"id": 555}, "text": "/start dead"}

    with (
        patch("app.telegram_bot.consume_tg_link_code", new=AsyncMock(return_value=None)),
        patch("app.telegram_bot._link_user", new=AsyncMock()) as link_mock,
        patch("app.telegram_bot._send", new=AsyncMock()) as send_mock,
    ):
        await _handle_message(client_mock, message)

    link_mock.assert_not_awaited()
    text = send_mock.call_args[0][2]
    assert "истёк" in text.lower() or "неверен" in text.lower()


async def test_bot_handle_start_without_code_sends_help():
    """`/start` без кода → шлём подсказку."""
    from app.telegram_bot import _handle_message

    client_mock = AsyncMock()
    message = {"chat": {"id": 555}, "text": "/start"}

    with (
        patch("app.telegram_bot.consume_tg_link_code", new=AsyncMock()) as consume_mock,
        patch("app.telegram_bot._send", new=AsyncMock()) as send_mock,
    ):
        await _handle_message(client_mock, message)

    consume_mock.assert_not_awaited()
    text = send_mock.call_args[0][2]
    assert "/start" in text


async def test_bot_handle_unrelated_text_ignored():
    """Произвольный текст без `/start` — игнорируем, ничего не шлём."""
    from app.telegram_bot import _handle_message

    client_mock = AsyncMock()
    message = {"chat": {"id": 555}, "text": "hi bot"}

    with patch("app.telegram_bot._send", new=AsyncMock()) as send_mock:
        await _handle_message(client_mock, message)

    send_mock.assert_not_awaited()


async def test_threshold_enqueues_telegram_alert_on_trigger():
    """evaluate_system_metrics должен вызвать send_telegram_alert.delay после commit."""
    from app.models.alert_rule import ThresholdOperator
    from app.services.threshold import evaluate_system_metrics

    db = AsyncMock()
    db.add = MagicMock()

    rule = MagicMock(
        id=1,
        metric_field="cpu_percent",
        operator=ThresholdOperator.gt,
        threshold_value=90.0,
        last_triggered_at=None,
        cooldown_seconds=300,
    )
    rule.name = "cpu high"
    scalars = MagicMock()
    scalars.scalars.return_value.all.return_value = [rule]
    db.execute.return_value = scalars

    with (
        patch("app.tasks.notification_tasks.send_telegram_alert.delay") as delay_mock,
        patch("app.services.threshold.publish_alert", new=AsyncMock()),
    ):
        events = await evaluate_system_metrics(db, server_id=1, metric_data={"cpu_percent": 95.0})

    assert len(events) == 1
    delay_mock.assert_called_once()
