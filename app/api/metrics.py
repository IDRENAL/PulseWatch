from fastapi import APIRouter, Depends, status
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import verify_api_key
from app.database import get_db
from app.models.metric import Metric
from app.models.server import Server
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
    return {"status": "ok"}
