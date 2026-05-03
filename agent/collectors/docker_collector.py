import docker
from docker.errors import DockerException
from docker.models.containers import Container
from loguru import logger

_BYTES_IN_MB = 1024 * 1024


def _calculate_cpu_percent(stats: dict) -> float:
    """CPU% по разности cpu_stats и precpu_stats (как делает `docker stats`)."""
    cpu_stats = stats.get("cpu_stats", {})
    precpu_stats = stats.get("precpu_stats", {})

    cpu_usage = cpu_stats.get("cpu_usage", {})
    precpu_usage = precpu_stats.get("cpu_usage", {})

    cpu_total = cpu_usage.get("total_usage", 0)
    precpu_total = precpu_usage.get("total_usage", 0)
    cpu_delta = cpu_total - precpu_total

    system_cpu = cpu_stats.get("system_cpu_usage", 0)
    presystem_cpu = precpu_stats.get("system_cpu_usage", 0)
    system_delta = system_cpu - presystem_cpu

    online_cpus = (
        cpu_stats.get("online_cpus")
        or len(cpu_usage.get("percpu_usage") or [])
        or 1
    )

    if system_delta <= 0 or cpu_delta < 0:
        return 0.0
    return (cpu_delta / system_delta) * online_cpus * 100.0


def _container_image(container: Container) -> str:
    """Имя образа из container.attrs — не лезет в /images, не падает на orphan'ах."""
    config = container.attrs.get("Config", {}) or {}
    image = config.get("Image") or container.attrs.get("Image") or ""
    return image.removeprefix("sha256:") if image.startswith("sha256:") else image


def _container_memory_limit_mb(container: Container) -> float | None:
    """Лимит из HostConfig.Memory. 0 = не задан → None."""
    host_config = container.attrs.get("HostConfig", {}) or {}
    mem_limit_bytes = host_config.get("Memory") or 0
    if mem_limit_bytes <= 0:
        return None
    return mem_limit_bytes / _BYTES_IN_MB


def _collect_one(container: Container) -> dict:
    container_id = container.short_id
    container_name = container.name or ""
    image = _container_image(container)
    status = container.status

    if status != "running":
        return {
            "container_id": container_id,
            "container_name": container_name,
            "image": image,
            "status": status,
            "cpu_percent": 0.0,
            "memory_usage_mb": 0.0,
            "memory_limit_mb": _container_memory_limit_mb(container),
        }

    # stream=False обязательно — иначе stats() возвращает генератор и зависает.
    stats = container.stats(stream=False)
    cpu_percent = _calculate_cpu_percent(stats)
    memory_stats = stats.get("memory_stats", {}) or {}
    memory_usage_bytes = memory_stats.get("usage", 0) or 0

    return {
        "container_id": container_id,
        "container_name": container_name,
        "image": image,
        "status": status,
        "cpu_percent": cpu_percent,
        "memory_usage_mb": memory_usage_bytes / _BYTES_IN_MB,
        "memory_limit_mb": _container_memory_limit_mb(container),
    }


def collect_docker_metrics() -> list[dict]:
    try:
        client = docker.from_env()
    except DockerException as exc:
        logger.warning("Docker daemon недоступен: {}", exc)
        return []

    try:
        containers = client.containers.list(all=True)
    except DockerException as exc:
        logger.warning("Не удалось получить список контейнеров: {}", exc)
        client.close()
        return []

    metrics: list[dict] = []
    for container in containers:
        try:
            metrics.append(_collect_one(container))
        except DockerException as exc:
            logger.warning(
                "Сбой при сборе метрик контейнера {}: {}", container.short_id, exc
            )

    client.close()
    return metrics
