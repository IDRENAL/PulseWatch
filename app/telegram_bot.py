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
from app.models.alert_rule import AlertRule, MetricType, ThresholdOperator
from app.models.metric import Metric
from app.models.server import Server
from app.models.user import User
from app.redis_client import (
    MUTE_CHANNELS,
    clear_rule_draft,
    consume_pending_delete,
    consume_tg_link_code,
    get_channel_mute_ttl,
    get_rule_draft,
    set_channel_mute,
    set_pending_delete,
    set_redis_client,
    set_rule_draft,
)

_POLL_TIMEOUT_SECONDS = 30
_HTTP_TIMEOUT = httpx.Timeout(_POLL_TIMEOUT_SECONDS + 10, connect=10.0)
_START_PATTERN = re.compile(r"^/start\s+(?P<code>\S+)\s*$")
_MUTE_PATTERN = re.compile(
    r"^/mute\s+(?P<server_id>\d+)\s+(?P<minutes>\d+)(?:\s+(?P<channel>\w+))?\s*$"
)
_TOGGLE_PATTERN = re.compile(r"^/toggle\s+(?P<rule_id>\d+)\s*$")
_DELETE_PATTERN = re.compile(r"^/delete\s+(?P<server_id>\d+)(?P<confirm>\s+confirm)?\s*$")
_EVENTS_PATTERN = re.compile(r"^/events(?:\s+(?P<server_id>\d+))?\s*$")
_EVENTS_LIMIT = 10
_PAUSE_PATTERN = re.compile(r"^/pause\s+(?P<server_id>\d+)\s*$")
_RESUME_PATTERN = re.compile(r"^/resume\s+(?P<server_id>\d+)\s*$")

# /createrule — диалоговое создание правила. Только system-метрики (cpu/mem/disk).
# Docker-правила (с container_name) — через REST, чтобы не плодить шаги диалога.
_METRIC_FIELDS = ("cpu_percent", "memory_percent", "disk_percent")
_OPERATORS = ("gt", "gte", "lt", "lte", "eq", "neq")
_CHANNEL_PRESETS = {
    "telegram": ["telegram"],
    "email": ["email"],
    "both": ["telegram", "email"],
    "none": [],
}


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
            "Команды:\n"
            "  /status, /servers\n"
            "  /mute <server_id> <minutes> [telegram|email|all]\n"
            "  /rules, /toggle <rule_id>, /createrule\n"
            "  /delete <server_id>\n"
            "  /events [server_id]\n"
            "  /pause <server_id>, /resume <server_id>",
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

            if server.paused:
                metric_part = "⏸ paused"
            elif latest:
                metric_part = (
                    f"cpu={latest.cpu_percent:.1f}% mem={latest.memory_percent:.1f}% "
                    f"disk={latest.disk_percent:.1f}%"
                )
            else:
                metric_part = "нет данных"
            mute_parts = []
            for ch in MUTE_CHANNELS:
                ttl = await get_channel_mute_ttl(server.id, ch)
                if ttl:
                    mute_parts.append(f"{ch[:2]}:{ttl // 60}m")
            mute_part = f" 🔇{' '.join(mute_parts)}" if mute_parts else ""
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
        if server.paused:
            state = "⏸ paused"
        elif server.is_active:
            state = "✅ active"
        else:
            state = "❌ down"
        lines.append(f"• #{server.id} {server.name} {state} last_seen={seen}")
    await _send(client, chat_id, "\n".join(lines))


# ─── Команда /mute <server_id> <minutes> ─────────────────────────────────────


async def _handle_mute(client: httpx.AsyncClient, chat_id: int, user: User, text: str) -> None:
    match = _MUTE_PATTERN.match(text)
    if not match:
        await _send(
            client,
            chat_id,
            "Использование: /mute <server_id> <minutes> [telegram|email|all]",
        )
        return

    server_id = int(match.group("server_id"))
    minutes = int(match.group("minutes"))
    channel_arg = (match.group("channel") or "all").lower()

    if minutes <= 0 or minutes > 1440:
        await _send(client, chat_id, "❌ minutes должен быть в диапазоне 1..1440")
        return

    if channel_arg not in {"all", *MUTE_CHANNELS}:
        await _send(
            client,
            chat_id,
            f"❌ Неверный канал. Допустимо: all, {', '.join(MUTE_CHANNELS)}",
        )
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

    channels = MUTE_CHANNELS if channel_arg == "all" else (channel_arg,)
    for ch in channels:
        await set_channel_mute(server_id, ch, minutes)

    channels_str = ", ".join(channels)
    await _send(
        client,
        chat_id,
        f"🔇 Сервер #{server_id} {server.name} заглушен на {minutes} мин ({channels_str}).",
    )


# ─── Команда /rules — список правил юзера ───────────────────────────────────


async def _handle_rules(client: httpx.AsyncClient, chat_id: int, user: User) -> None:
    async with async_session_factory() as db:
        rules = (
            (
                await db.execute(
                    select(AlertRule, Server.name)
                    .join(Server, Server.id == AlertRule.server_id)
                    .where(AlertRule.owner_id == user.id)
                    .order_by(AlertRule.id)
                )
            )
            .tuples()
            .all()
        )

    if not rules:
        await _send(client, chat_id, "У тебя нет правил.")
        return

    lines = [f"📐 Правила ({len(rules)}):"]
    for rule, server_name in rules:
        state = "✅on" if rule.is_active else "⏸off"
        op = rule.operator.value
        lines.append(
            f"• #{rule.id} {state} [{server_name}] {rule.name}: "
            f"{rule.metric_field} {op} {rule.threshold_value}"
        )
    await _send(client, chat_id, "\n".join(lines))


# ─── Команда /toggle <rule_id> — флип is_active ─────────────────────────────


async def _handle_toggle(client: httpx.AsyncClient, chat_id: int, user: User, text: str) -> None:
    match = _TOGGLE_PATTERN.match(text)
    if not match:
        await _send(client, chat_id, "Использование: /toggle <rule_id>")
        return

    rule_id = int(match.group("rule_id"))
    async with async_session_factory() as db:
        rule = (
            await db.execute(
                select(AlertRule).where(AlertRule.id == rule_id, AlertRule.owner_id == user.id)
            )
        ).scalar_one_or_none()
        if rule is None:
            await _send(client, chat_id, "❌ Правило не найдено или не твоё.")
            return

        rule.is_active = not rule.is_active
        await db.commit()
        new_state = "✅on" if rule.is_active else "⏸off"
        await _send(client, chat_id, f"Правило #{rule.id} «{rule.name}» теперь {new_state}")


# ─── Команда /delete <server_id> [confirm] — двухступенчатое удаление ───────


async def _handle_delete(client: httpx.AsyncClient, chat_id: int, user: User, text: str) -> None:
    match = _DELETE_PATTERN.match(text)
    if not match:
        await _send(client, chat_id, "Использование: /delete <server_id>")
        return

    server_id = int(match.group("server_id"))
    is_confirm = match.group("confirm") is not None

    async with async_session_factory() as db:
        server = (
            await db.execute(
                select(Server).where(Server.id == server_id, Server.owner_id == user.id)
            )
        ).scalar_one_or_none()
        if server is None:
            await _send(client, chat_id, "❌ Сервер не найден или не твой.")
            return

        if not is_confirm:
            await set_pending_delete(chat_id, server_id)
            await _send(
                client,
                chat_id,
                f"⚠️ Удалить сервер #{server.id} «{server.name}»?\n"
                f"Это снесёт все его метрики, агрегаты, правила и события — необратимо.\n"
                f"Подтверди в течение 60с: /delete {server.id} confirm",
            )
            return

        if not await consume_pending_delete(chat_id, server_id):
            await _send(
                client,
                chat_id,
                "❌ Подтверждение истекло или не совпадает. Начни заново: /delete <id>",
            )
            return

        server_name = server.name
        await db.delete(server)
        await db.commit()
        await _send(client, chat_id, f"🗑 Сервер #{server_id} «{server_name}» удалён.")


# ─── Команда /events [server_id] — последние срабатывания ──────────────────


async def _handle_events(client: httpx.AsyncClient, chat_id: int, user: User, text: str) -> None:
    match = _EVENTS_PATTERN.match(text)
    if not match:
        await _send(client, chat_id, "Использование: /events [server_id]")
        return

    server_id_raw = match.group("server_id")
    server_id = int(server_id_raw) if server_id_raw else None

    stmt = (
        select(AlertEvent, AlertRule.name, Server.name)
        .join(AlertRule, AlertRule.id == AlertEvent.rule_id)
        .join(Server, Server.id == AlertEvent.server_id)
        .where(Server.owner_id == user.id)
        .order_by(AlertEvent.created_at.desc())
        .limit(_EVENTS_LIMIT)
    )
    if server_id is not None:
        stmt = stmt.where(AlertEvent.server_id == server_id)

    async with async_session_factory() as db:
        rows = (await db.execute(stmt)).tuples().all()

    if not rows:
        suffix = f" для сервера #{server_id}" if server_id else ""
        await _send(client, chat_id, f"Событий{suffix} нет.")
        return

    header = f"📜 Последние события (для #{server_id})" if server_id else "📜 Последние события"
    lines = [f"{header}, всего {len(rows)}:"]
    for event, rule_name, server_name in rows:
        status = "✅resolved" if event.resolved_at else "🔥open"
        ts = event.created_at.strftime("%m-%d %H:%M")
        lines.append(
            f"• #{event.id} [{server_name}] {rule_name}: "
            f"{event.metric_value} (порог {event.threshold_value}) | {status} | {ts}"
        )
    await _send(client, chat_id, "\n".join(lines))


# ─── Команды /pause /resume — тоггл Server.paused ──────────────────────────


async def _set_server_paused(
    client: httpx.AsyncClient,
    chat_id: int,
    user: User,
    text: str,
    pattern: re.Pattern,
    new_value: bool,
    usage: str,
) -> None:
    match = pattern.match(text)
    if not match:
        await _send(client, chat_id, usage)
        return

    server_id = int(match.group("server_id"))
    async with async_session_factory() as db:
        server = (
            await db.execute(
                select(Server).where(Server.id == server_id, Server.owner_id == user.id)
            )
        ).scalar_one_or_none()
        if server is None:
            await _send(client, chat_id, "❌ Сервер не найден или не твой.")
            return

        if server.paused == new_value:
            state = "уже на паузе" if new_value else "и так активен"
            await _send(client, chat_id, f"Сервер #{server_id} {server.name} {state}.")
            return

        server.paused = new_value
        await db.commit()
        action = (
            "⏸ Сервер #{} {} поставлен на паузу." if new_value else "▶ Сервер #{} {} снят с паузы."
        )
        await _send(client, chat_id, action.format(server_id, server.name))


async def _handle_pause(client: httpx.AsyncClient, chat_id: int, user: User, text: str) -> None:
    await _set_server_paused(
        client, chat_id, user, text, _PAUSE_PATTERN, True, "Использование: /pause <server_id>"
    )


async def _handle_resume(client: httpx.AsyncClient, chat_id: int, user: User, text: str) -> None:
    await _set_server_paused(
        client, chat_id, user, text, _RESUME_PATTERN, False, "Использование: /resume <server_id>"
    )


# ─── /createrule — диалоговое создание правила (state-машина в Redis) ──────


async def _handle_createrule_start(client: httpx.AsyncClient, chat_id: int, user: User) -> None:
    """Старт диалога. Текущий черновик (если был) сбрасываем."""
    async with async_session_factory() as db:
        servers = (
            (await db.execute(select(Server).where(Server.owner_id == user.id))).scalars().all()
        )
    if not servers:
        await _send(
            client, chat_id, "❌ У тебя нет серверов. Зарегистрируй через POST /servers/register."
        )
        return

    await set_rule_draft(chat_id, {"step": "server", "data": {}})
    lines = ["📝 Создание правила (system-метрики).\nНа каком сервере? Твои:"]
    for s in servers:
        lines.append(f"  #{s.id} {s.name}")
    lines.append("Введи id сервера. Любой момент можно прервать через /cancel.")
    await _send(client, chat_id, "\n".join(lines))


async def _handle_cancel(client: httpx.AsyncClient, chat_id: int) -> None:
    await clear_rule_draft(chat_id)
    await _send(client, chat_id, "Черновик отменён.")


async def _process_rule_draft(
    client: httpx.AsyncClient, chat_id: int, user: User, text: str, draft: dict
) -> None:
    """Обработка одного шага диалога. На каждом шаге парсим вход, валидируем,
    если ок — двигаемся к следующему шагу, если нет — повторяем вопрос с подсказкой.
    """
    step = draft["step"]
    data = draft["data"]
    text = text.strip()

    if step == "server":
        if not text.isdigit():
            await _send(client, chat_id, "❌ Нужно число — id сервера.")
            return
        server_id = int(text)
        async with async_session_factory() as db:
            server = (
                await db.execute(
                    select(Server).where(Server.id == server_id, Server.owner_id == user.id)
                )
            ).scalar_one_or_none()
        if server is None:
            await _send(client, chat_id, "❌ Сервер не найден или не твой. Введи id ещё раз.")
            return
        data["server_id"] = server_id
        data["server_name"] = server.name
        draft["step"] = "name"
        await set_rule_draft(chat_id, draft)
        await _send(client, chat_id, "Как назвать правило? (свободный текст)")
        return

    if step == "name":
        if not text or len(text) > 255:
            await _send(client, chat_id, "❌ Имя должно быть от 1 до 255 символов.")
            return
        data["name"] = text
        draft["step"] = "metric"
        await set_rule_draft(chat_id, draft)
        await _send(
            client,
            chat_id,
            f"Какая метрика? Доступно: {', '.join(_METRIC_FIELDS)}",
        )
        return

    if step == "metric":
        metric = text.lower()
        if metric not in _METRIC_FIELDS:
            await _send(client, chat_id, f"❌ Допустимо: {', '.join(_METRIC_FIELDS)}")
            return
        data["metric_field"] = metric
        draft["step"] = "operator"
        await set_rule_draft(chat_id, draft)
        await _send(client, chat_id, f"Оператор? {', '.join(_OPERATORS)}")
        return

    if step == "operator":
        op = text.lower()
        if op not in _OPERATORS:
            await _send(client, chat_id, f"❌ Допустимо: {', '.join(_OPERATORS)}")
            return
        data["operator"] = op
        draft["step"] = "threshold"
        await set_rule_draft(chat_id, draft)
        await _send(client, chat_id, "Порог? (число, например 80 или 0.75)")
        return

    if step == "threshold":
        try:
            value = float(text)
        except ValueError:
            await _send(client, chat_id, "❌ Не понимаю, нужно число.")
            return
        data["threshold_value"] = value
        draft["step"] = "channels"
        await set_rule_draft(chat_id, draft)
        await _send(
            client,
            chat_id,
            "Куда слать уведомления? telegram / email / both / none",
        )
        return

    if step == "channels":
        preset = text.lower()
        if preset not in _CHANNEL_PRESETS:
            await _send(client, chat_id, "❌ Допустимо: telegram, email, both, none")
            return
        data["notification_channels"] = _CHANNEL_PRESETS[preset]
        draft["step"] = "confirm"
        await set_rule_draft(chat_id, draft)
        channels_str = ", ".join(data["notification_channels"]) or "—"
        summary = (
            "Проверь:\n"
            f"  сервер: #{data['server_id']} {data['server_name']}\n"
            f"  имя: {data['name']}\n"
            f"  условие: {data['metric_field']} {data['operator']} {data['threshold_value']}\n"
            f"  каналы: {channels_str}\n"
            "Создать? y / n"
        )
        await _send(client, chat_id, summary)
        return

    if step == "confirm":
        if text.lower() in ("n", "no", "нет"):
            await clear_rule_draft(chat_id)
            await _send(client, chat_id, "Отменено, ничего не создал.")
            return
        if text.lower() not in ("y", "yes", "да"):
            await _send(client, chat_id, "Ответь y или n.")
            return

        # Создаём правило
        async with async_session_factory() as db:
            rule = AlertRule(
                server_id=data["server_id"],
                owner_id=user.id,
                name=data["name"],
                metric_type=MetricType.system,
                metric_field=data["metric_field"],
                operator=ThresholdOperator(data["operator"]),
                threshold_value=data["threshold_value"],
                notification_channels=data["notification_channels"],
            )
            db.add(rule)
            await db.commit()
            await db.refresh(rule)

        await clear_rule_draft(chat_id)
        await _send(client, chat_id, f"✅ Правило #{rule.id} «{rule.name}» создано.")
        return

    # Неизвестный шаг — лечим сбросом
    logger.warning("rule_draft: unknown step {} for chat_id={}", step, chat_id)
    await clear_rule_draft(chat_id)
    await _send(
        client, chat_id, "Что-то пошло не так, черновик сброшен. /createrule чтобы начать заново."
    )


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

    # Все остальные команды (и draft-ответы) требуют привязанного юзера
    async with async_session_factory() as db:
        user = await _find_user_by_chat_id(db, chat_id)
    if user is None:
        if text.startswith("/"):
            await _send(
                client,
                chat_id,
                "Этот чат не привязан к аккаунту. Получи код через "
                "POST /auth/me/telegram/code и отправь /start <код>.",
            )
        return

    # /cancel сбрасывает активный черновик (если есть) и выходит
    if text.startswith("/cancel"):
        await _handle_cancel(client, chat_id)
        return

    # Активный черновик правила перехватывает не-слеш-сообщения
    draft = await get_rule_draft(chat_id)
    if draft is not None and not text.startswith("/"):
        await _process_rule_draft(client, chat_id, user, text, draft)
        return

    # Слеш-команда при активном черновике — отменяем диалог (явный exit от юзера)
    if draft is not None and text.startswith("/"):
        await clear_rule_draft(chat_id)

    if not text.startswith("/"):
        return  # обычный текст без активного черновика — игнор

    if text.startswith("/status"):
        await _handle_status(client, chat_id, user)
    elif text.startswith("/servers"):
        await _handle_servers(client, chat_id, user)
    elif text.startswith("/mute"):
        await _handle_mute(client, chat_id, user, text)
    elif text.startswith("/rules"):
        await _handle_rules(client, chat_id, user)
    elif text.startswith("/toggle"):
        await _handle_toggle(client, chat_id, user, text)
    elif text.startswith("/delete"):
        await _handle_delete(client, chat_id, user, text)
    elif text.startswith("/events"):
        await _handle_events(client, chat_id, user, text)
    elif text.startswith("/pause"):
        await _handle_pause(client, chat_id, user, text)
    elif text.startswith("/resume"):
        await _handle_resume(client, chat_id, user, text)
    elif text.startswith("/createrule"):
        await _handle_createrule_start(client, chat_id, user)
    else:
        await _send(
            client,
            chat_id,
            "Неизвестная команда. Доступные:\n"
            "  /status, /servers\n"
            "  /mute <server_id> <minutes> [telegram|email|all]\n"
            "  /rules, /toggle <rule_id>, /createrule\n"
            "  /delete <server_id>\n"
            "  /events [server_id]\n"
            "  /pause <server_id>, /resume <server_id>\n"
            "  /cancel — прервать диалог /createrule",
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
