import json

from redis.asyncio import Redis

# Ссылка на Redis-клиент, устанавливается в lifespan (app/main.py).
# Используется только в контекстах, где Request недоступен (WebSocket, background).
_redis_client: Redis | None = None


def _get_app_redis() -> Redis:
    """Внутренний доступ к Redis-клиенту через глобальную ссылку."""
    if _redis_client is None:
        raise RuntimeError("redis not initialized")
    return _redis_client


def set_redis_client(client: Redis | None) -> None:
    """Устанавливает/сбрасывает глобальную ссылку на Redis-клиент."""
    global _redis_client
    _redis_client = client


async def publish_metric(server_id: int, data: dict) -> None:
    """Публикует системную метрику в Redis-канал metrics:{server_id}."""
    r = _get_app_redis()
    payload = json.dumps({"type": "metric", "server_id": server_id, **data})
    await r.publish(f"metrics:{server_id}", payload)


async def publish_docker_metric(server_id: int, data: list[dict]) -> None:
    """Публикует Docker-метрики в Redis-канал docker_metrics:{server_id}."""
    r = _get_app_redis()
    payload = json.dumps({"type": "docker_metric", "server_id": server_id, "containers": data})
    await r.publish(f"docker_metrics:{server_id}", payload)


async def publish_alert(server_id: int, data: dict) -> None:
    """Публикует событие алерта в Redis-канал alerts:{server_id}."""
    r = _get_app_redis()
    payload = json.dumps({"type": "alert", "server_id": server_id, **data})
    await r.publish(f"alerts:{server_id}", payload)


async def cache_dashboard(user_id: int, data: str, ttl: int = 10) -> None:
    """Кэширует сводную информацию дашборда в Redis на ttl секунд."""
    r = _get_app_redis()
    await r.set(f"dashboard:{user_id}", data, ex=ttl)


async def get_cached_dashboard(user_id: int) -> str | None:
    """Возвращает кэшированный дашборд или None."""
    r = _get_app_redis()
    return await r.get(f"dashboard:{user_id}")


def get_redis() -> Redis:
    """Публичный доступ к Redis-клиенту (для WS и health)."""
    return _get_app_redis()


# ─── Telegram /start link codes ─────────────────────────────────────────────

_TG_LINK_CODE_TTL_SECONDS = 600  # 10 минут


def _tg_link_key(code: str) -> str:
    return f"tg:linkcode:{code}"


async def store_tg_link_code(code: str, user_id: int) -> None:
    """Сохраняет одноразовый код привязки Telegram с TTL 10 мин."""
    r = _get_app_redis()
    await r.set(_tg_link_key(code), str(user_id), ex=_TG_LINK_CODE_TTL_SECONDS)


async def consume_tg_link_code(code: str) -> int | None:
    """Извлекает user_id по коду и сразу удаляет код (одноразовый).

    Returns user_id или None если код не найден / истёк.
    """
    r = _get_app_redis()
    key = _tg_link_key(code)
    pipe = r.pipeline()
    pipe.get(key)
    pipe.delete(key)
    raw_user_id, _ = await pipe.execute()
    if raw_user_id is None:
        return None
    return int(raw_user_id)


# ─── Per-channel mute (заглушка уведомлений по каналам) ─────────────────────

MUTE_CHANNELS = ("telegram", "email")


def _mute_key(server_id: int, channel: str) -> str:
    return f"mute:{server_id}:{channel}"


async def set_channel_mute(server_id: int, channel: str, minutes: int) -> None:
    """Глушит конкретный канал уведомлений для сервера на N минут (Redis SETEX)."""
    r = _get_app_redis()
    await r.set(_mute_key(server_id, channel), "1", ex=minutes * 60)


async def is_channel_muted(server_id: int, channel: str) -> bool:
    """True, если активна заглушка для (server, channel)."""
    r = _get_app_redis()
    return await r.exists(_mute_key(server_id, channel)) == 1


async def get_channel_mute_ttl(server_id: int, channel: str) -> int | None:
    """TTL заглушки конкретного канала в секундах или None если её нет."""
    r = _get_app_redis()
    ttl = await r.ttl(_mute_key(server_id, channel))
    return ttl if ttl > 0 else None


# ─── Pending delete confirmation (бот /delete) ──────────────────────────────

_PENDING_DELETE_TTL_SECONDS = 60


def _pending_delete_key(chat_id: int) -> str:
    return f"pending_delete:{chat_id}"


async def set_pending_delete(chat_id: int, server_id: int) -> None:
    """Запоминает намерение удалить сервер на 60с. Ключ — chat_id (один pending на чат)."""
    r = _get_app_redis()
    await r.set(_pending_delete_key(chat_id), str(server_id), ex=_PENDING_DELETE_TTL_SECONDS)


async def consume_pending_delete(chat_id: int, server_id: int) -> bool:
    """Проверяет, что pending для chat_id совпадает с server_id, и удаляет ключ.

    Returns True если совпало (можно удалять), False если нет/истёк.
    """
    r = _get_app_redis()
    key = _pending_delete_key(chat_id)
    pipe = r.pipeline()
    pipe.get(key)
    pipe.delete(key)
    raw, _ = await pipe.execute()
    return raw is not None and int(raw) == server_id


# ─── Refresh-токены: whitelist в Redis ──────────────────────────────────────


def _refresh_key(user_id: int, jti: str) -> str:
    return f"refresh:{user_id}:{jti}"


def _refresh_used_key(user_id: int, jti: str) -> str:
    """Ключ-«трупик»: jti уже потрачен на ротацию. Живёт до конца TTL токена,
    чтобы можно было заметить попытку повторного использования."""
    return f"refresh_used:{user_id}:{jti}"


async def store_refresh_jti(user_id: int, jti: str, ttl_seconds: int) -> None:
    """Добавляет jti в whitelist на ttl_seconds. После TTL ключ умирает сам — даже
    если мы забыли его явно отозвать.
    """
    r = _get_app_redis()
    await r.set(_refresh_key(user_id, jti), "1", ex=ttl_seconds)


async def is_refresh_jti_valid(user_id: int, jti: str) -> bool:
    """True, если jti в whitelist (не отозван и не истёк)."""
    r = _get_app_redis()
    return await r.exists(_refresh_key(user_id, jti)) == 1


async def is_refresh_jti_used(user_id: int, jti: str) -> bool:
    """True, если jti уже был использован для ротации. Сигнал к reuse-detection."""
    r = _get_app_redis()
    return await r.exists(_refresh_used_key(user_id, jti)) == 1


async def revoke_refresh_jti(user_id: int, jti: str) -> None:
    """Удаляет jti из whitelist (logout или ротация)."""
    r = _get_app_redis()
    await r.delete(_refresh_key(user_id, jti))


async def rotate_refresh_jti(user_id: int, old_jti: str, new_jti: str, ttl_seconds: int) -> bool:
    """Атомарно отзывает old_jti и ставит new_jti. True если old_jti был валиден.

    Если ротация прошла — помечаем old_jti как «использованный» с TTL=TTL токена,
    чтобы reuse-detection в `/auth/refresh` мог поймать повторное использование.
    """
    r = _get_app_redis()
    old_key = _refresh_key(user_id, old_jti)
    new_key = _refresh_key(user_id, new_jti)
    pipe = r.pipeline()
    pipe.delete(old_key)
    pipe.set(new_key, "1", ex=ttl_seconds)
    deleted, _ = await pipe.execute()
    if deleted == 1:
        await r.set(_refresh_used_key(user_id, old_jti), "1", ex=ttl_seconds)
        return True
    return False


# ─── Bot: черновик правила в /createrule ────────────────────────────────────

_RULE_DRAFT_TTL_SECONDS = 600  # 10 минут — диалог не должен затянуться


def _rule_draft_key(chat_id: int) -> str:
    return f"rule_draft:{chat_id}"


async def set_rule_draft(chat_id: int, draft: dict) -> None:
    """Сохраняет состояние черновика (step + накопленные поля) на 10 минут."""
    r = _get_app_redis()
    await r.set(_rule_draft_key(chat_id), json.dumps(draft), ex=_RULE_DRAFT_TTL_SECONDS)


async def get_rule_draft(chat_id: int) -> dict | None:
    """Возвращает текущий черновик или None если его нет/истёк."""
    r = _get_app_redis()
    raw = await r.get(_rule_draft_key(chat_id))
    return json.loads(raw) if raw else None


async def clear_rule_draft(chat_id: int) -> None:
    """Удаляет черновик (cancel или после успешного создания)."""
    r = _get_app_redis()
    await r.delete(_rule_draft_key(chat_id))


# ─── Password reset: одноразовые токены ─────────────────────────────────────


def _password_reset_key(token: str) -> str:
    return f"pwd_reset:{token}"


async def store_password_reset_token(token: str, user_id: int, ttl_seconds: int) -> None:
    """Сохраняет токен → user_id на ttl_seconds."""
    r = _get_app_redis()
    await r.set(_password_reset_key(token), str(user_id), ex=ttl_seconds)


async def consume_password_reset_token(token: str) -> int | None:
    """Извлекает user_id по токену и сразу удаляет ключ (одноразовость).

    Возвращает user_id или None если не нашли / истёк.
    """
    r = _get_app_redis()
    key = _password_reset_key(token)
    pipe = r.pipeline()
    pipe.get(key)
    pipe.delete(key)
    raw, _ = await pipe.execute()
    return int(raw) if raw is not None else None


async def revoke_all_refresh_for_user(user_id: int) -> int:
    """Стирает все активные refresh-токены юзера. Возвращает число удалённых.

    Используется при reuse-detection — выкидываем все сессии, потому что не знаем
    какая из них скомпрометирована.
    """
    r = _get_app_redis()
    deleted = 0
    async for key in r.scan_iter(match=f"refresh:{user_id}:*", count=100):
        await r.delete(key)
        deleted += 1
    return deleted
