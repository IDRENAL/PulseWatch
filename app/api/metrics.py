import json

from fastapi import APIRouter, Depends, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import verify_api_key
from app.database import get_db
from app.models.metric import Metric
from app.models.server import Server
from app.redis_client import publish_metric
from app.schemas.metric import MetricCreate

router = APIRouter()


@router.post("", status_code=status.HTTP_201_CREATED)
async def submit_metric(
    data: MetricCreate,
    server: Server = Depends(verify_api_key),
    db: AsyncSession = Depends(get_db),
):
    new_metric = Metric(
        server_id=server.id,
        cpu_percent=data.cpu_percent,
        memory_percent=data.memory_percent,
        disk_percent=data.disk_percent,
    )
    db.add(new_metric)

    server.last_seen_at = func.now()

    await db.commit()
    await db.refresh(new_metric)

    # Публикуем метрику в Redis Pub/Sub для real-time дашборда
    try:
        await publish_metric(
            server_id=server.id,
            data={
                "id": new_metric.id,
                "cpu_percent": new_metric.cpu_percent,
                "memory_percent": new_metric.memory_percent,
                "disk_percent": new_metric.disk_percent,
                "collected_at": new_metric.collected_at.isoformat(),
            },
        )
    except Exception:
        # Pub/Sub failure не должен блокировать приём метрик
        pass

    return {"status": "ok"}
