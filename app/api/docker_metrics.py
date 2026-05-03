from fastapi import APIRouter, Depends, status
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import verify_api_key
from app.database import get_db
from app.models.docker_metric import DockerMetric
from app.models.server import Server
from app.schemas.docker_metric import DockerMetricCreate

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
    return {"status": "ok", "count": len(rows)}
