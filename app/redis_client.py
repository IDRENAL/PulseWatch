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
    payload = json.dumps(
        {"type": "docker_metric", "server_id": server_id, "containers": data}
    )
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
