import json
import secrets

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from app.database import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.models.server import Server
from app.models.metric import Metric
from app.models.docker_metric import DockerMetric
from app.schemas.server import ServerCreate, ServerRead, ServerWithKey
from app.schemas.metric import MetricRead
from app.schemas.docker_metric import DockerMetricRead
from app.schemas.metric_aggregate import MetricAggregateRead
from app.schemas.docker_aggregate import DockerAggregateRead
from app.models.metric_aggregate import MetricAggregate, PeriodType as AggregatePeriodType
from app.models.docker_aggregate import DockerAggregate
from app.core.security import hash_password
from app.redis_client import cache_dashboard, get_cached_dashboard

router = APIRouter()


@router.post("/register", response_model=ServerWithKey, status_code=status.HTTP_201_CREATED)
async def register_server(
    data: ServerCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    secret = secrets.token_urlsafe(32)

    new_server = Server(
        name=data.name,
        api_key_hash=hash_password(secret),
        owner_id=current_user.id,
    )

    db.add(new_server)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Сервер с таким именем уже существует",
        )
    await db.refresh(new_server)

    api_key = f"{new_server.id}.{secret}"

    return ServerWithKey(
        id=new_server.id,
        name=new_server.name,
        is_active=new_server.is_active,
        created_at=new_server.created_at,
        last_seen_at=new_server.last_seen_at,
        api_key=api_key,
    )


@router.get("/me", response_model=list[ServerRead])
async def list_my_servers(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(Server).where(Server.owner_id == current_user.id)
    result = await db.execute(query)
    servers = result.scalars().all()
    return servers


@router.get("/dashboard")
async def dashboard(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Сводная информация по всем серверам пользователя с последними метриками.
    Результат кэшируется в Redis на 10 секунд.
    """
    cache_key = f"dashboard:{current_user.id}"

    # Проверяем кэш
    try:
        cached = await get_cached_dashboard(current_user.id)
        if cached is not None:
            return json.loads(cached)
    except Exception:
        pass

    # Запрашиваем серверы пользователя
    servers_query = select(Server).where(Server.owner_id == current_user.id)
    servers_result = await db.execute(servers_query)
    servers = servers_result.scalars().all()

    # Один запрос для последних метрик всех серверов (N+1 → 2 запроса)
    server_ids = [s.id for s in servers]
    latest_metrics: dict[int, dict] = {}
    if server_ids:
        rn = func.row_number().over(
            partition_by=Metric.server_id,
            order_by=Metric.collected_at.desc(),
        ).label("rn")
        subq = (
            select(
                Metric.server_id,
                Metric.cpu_percent,
                Metric.memory_percent,
                Metric.disk_percent,
                Metric.collected_at,
                rn,
            )
            .where(Metric.server_id.in_(server_ids))
            .subquery()
        )
        metrics_rows = await db.execute(
            select(
                subq.c.server_id,
                subq.c.cpu_percent,
                subq.c.memory_percent,
                subq.c.disk_percent,
                subq.c.collected_at,
            ).where(subq.c.rn == 1)
        )
        for row in metrics_rows.all():
            latest_metrics[row.server_id] = {
                "cpu_percent": row.cpu_percent,
                "memory_percent": row.memory_percent,
                "disk_percent": row.disk_percent,
                "collected_at": row.collected_at.isoformat(),
            }

    dashboard_data = []
    for server in servers:
        server_info = {
            "id": server.id,
            "name": server.name,
            "is_active": server.is_active,
            "last_seen_at": server.last_seen_at.isoformat() if server.last_seen_at else None,
            "latest_metric": None,
        }

        if server.id in latest_metrics:
            server_info["latest_metric"] = latest_metrics[server.id]

        dashboard_data.append(server_info)

    # Кэшируем результат
    try:
        await cache_dashboard(current_user.id, json.dumps(dashboard_data), ttl=10)
    except Exception:
        pass

    return dashboard_data


@router.get("/{server_id}/metrics/aggregate", response_model=list[MetricAggregateRead])
async def get_system_aggregates(
    server_id: int,
    period: AggregatePeriodType = Query(default=AggregatePeriodType.hourly),
    limit: int = Query(default=24, ge=1, le=365),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Возвращает агрегированные системные метрики сервера."""
    server = (await db.execute(
        select(Server).where(Server.id == server_id, Server.owner_id == current_user.id)
    )).scalar_one_or_none()
    if server is None:
        raise HTTPException(status_code=404, detail="Сервер не найден")

    result = await db.execute(
        select(MetricAggregate)
        .where(
            MetricAggregate.server_id == server_id,
            MetricAggregate.period_type == period,
        )
        .order_by(MetricAggregate.period_start.desc())
        .limit(limit)
    )
    return result.scalars().all()


@router.get("/{server_id}/docker-metrics/aggregate", response_model=list[DockerAggregateRead])
async def get_docker_aggregates(
    server_id: int,
    period: AggregatePeriodType = Query(default=AggregatePeriodType.hourly),
    container_name: str | None = Query(default=None),
    limit: int = Query(default=24, ge=1, le=365),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Возвращает агрегированные Docker-метрики сервера."""
    server = (await db.execute(
        select(Server).where(Server.id == server_id, Server.owner_id == current_user.id)
    )).scalar_one_or_none()
    if server is None:
        raise HTTPException(status_code=404, detail="Сервер не найден")

    query = (
        select(DockerAggregate)
        .where(
            DockerAggregate.server_id == server_id,
            DockerAggregate.period_type == period,
        )
    )
    if container_name is not None:
        query = query.where(DockerAggregate.container_name == container_name)
    query = query.order_by(DockerAggregate.period_start.desc()).limit(limit)

    result = await db.execute(query)
    return result.scalars().all()


@router.get("/{server_id}/metrics", response_model=list[MetricRead])
async def list_server_metrics(
    server_id: int,
    limit: int = Query(default=100, ge=1, le=1000),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    server_query = select(Server).where(
        Server.id == server_id,
        Server.owner_id == current_user.id,
    )
    server = (await db.execute(server_query)).scalar_one_or_none()
    if server is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Server not found",
        )

    metrics_query = (
        select(Metric)
        .where(Metric.server_id == server_id)
        .order_by(Metric.collected_at.desc())
        .limit(limit)
    )
    result = await db.execute(metrics_query)
    return result.scalars().all()


@router.get(
    "/{server_id}/docker-metrics",
    response_model=list[DockerMetricRead],
)
async def list_server_docker_metrics(
    server_id: int,
    limit: int = Query(default=100, ge=1, le=1000),
    container_id: str | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    server_query = select(Server).where(
        Server.id == server_id,
        Server.owner_id == current_user.id,
    )
    server = (await db.execute(server_query)).scalar_one_or_none()
    if server is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Server not found",
        )

    metrics_query = select(DockerMetric).where(DockerMetric.server_id == server_id)
    if container_id is not None:
        metrics_query = metrics_query.where(
            DockerMetric.container_id == container_id
        )
    metrics_query = metrics_query.order_by(
        DockerMetric.collected_at.desc()
    ).limit(limit)

    result = await db.execute(metrics_query)
    return result.scalars().all()
