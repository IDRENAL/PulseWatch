from fastapi import APIRouter, Depends, status
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import verify_api_key
from app.database import get_db
from app.models.docker_metric import DockerMetric
from app.models.server import Server
from app.redis_client import publish_docker_metric
from app.schemas.docker_metric import DockerMetricCreate
from app.services.threshold import evaluate_docker_metrics

router = APIRouter()


@router.post("", status_code=status.HTTP_201_CREATED)
async def submit_docker_metrics(
    data: list[DockerMetricCreate],
    server: Server = Depends(verify_api_key),
    db: AsyncSession = Depends(get_db),
):
    rows = [
        DockerMetric(server_id=server.id, **item.model_dump()) for item in data
    ]
    db.add_all(rows)

    server.last_seen_at = func.now()

    await db.commit()

    # Проверяем docker-метрики против пороговых правил
    try:
        for item in data:
            await evaluate_docker_metrics(
                db,
                server_id=server.id,
                container_name=item.container_name,
                container_data={
                    "cpu_percent": item.cpu_percent,
                    "memory_usage_mb": item.memory_usage_mb,
                    "memory_limit_mb": item.memory_limit_mb,
                },
            )
    except Exception:
        pass  # Alert evaluation failure не должен блокировать приём метрик

    # Публикуем Docker-метрики в Redis Pub/Sub для real-time дашборда
    try:
        containers_data = [item.model_dump() for item in data]
        await publish_docker_metric(server_id=server.id, data=containers_data)
    except Exception:
        # Pub/Sub failure не должен блокировать приём метрик
        pass

    return {"status": "ok", "count": len(rows)}
