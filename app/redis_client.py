import json

from redis.asyncio import Redis

redis_client: Redis | None = None


def get_redis() -> Redis:
    if redis_client is None:
        raise RuntimeError("redis not initialized")
    return redis_client


async def publish_metric(server_id: int, data: dict) -> None:
    """Публикует системную метрику в Redis-канал metrics:{server_id}."""
    r = get_redis()
    payload = json.dumps({"type": "metric", "server_id": server_id, **data})
    await r.publish(f"metrics:{server_id}", payload)


async def publish_docker_metric(server_id: int, data: list[dict]) -> None:
    """Публикует Docker-метрики в Redis-канал docker_metrics:{server_id}."""
    r = get_redis()
    payload = json.dumps({"type": "docker_metric", "server_id": server_id, "containers": data})
    await r.publish(f"docker_metrics:{server_id}", payload)


async def cache_dashboard(user_id: int, data: str, ttl: int = 10) -> None:
    """Кэширует сводную информацию дашборда в Redis на ttl секунд."""
    r = get_redis()
    await r.set(f"dashboard:{user_id}", data, ex=ttl)


async def get_cached_dashboard(user_id: int) -> str | None:
    """Возвращает кэшированный дашборд или None."""
    r = get_redis()
    return await r.get(f"dashboard:{user_id}")
