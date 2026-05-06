import json
import secrets
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.security import hash_password
from app.database import get_db
from app.models.docker_aggregate import DockerAggregate
from app.models.docker_metric import DockerMetric
from app.models.metric import Metric
from app.models.metric_aggregate import MetricAggregate
from app.models.metric_aggregate import PeriodType as AggregatePeriodType
from app.models.server import Server
from app.models.user import User
from app.redis_client import cache_dashboard, get_cached_dashboard
from app.schemas.docker_aggregate import DockerAggregateRead
from app.schemas.docker_metric import DockerMetricRead
from app.schemas.metric import MetricRead
from app.schemas.metric_aggregate import MetricAggregateRead
from app.schemas.server import ServerCreate, ServerRead, ServerWithKey
from app.utils.csv_export import stream_csv

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
        ) from None
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
        rn = (
            func.row_number()
            .over(
                partition_by=Metric.server_id,
                order_by=Metric.collected_at.desc(),
            )
            .label("rn")
        )
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
    server = (
        await db.execute(
            select(Server).where(Server.id == server_id, Server.owner_id == current_user.id)
        )
    ).scalar_one_or_none()
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
    server = (
        await db.execute(
            select(Server).where(Server.id == server_id, Server.owner_id == current_user.id)
        )
    ).scalar_one_or_none()
    if server is None:
        raise HTTPException(status_code=404, detail="Сервер не найден")

    query = select(DockerAggregate).where(
        DockerAggregate.server_id == server_id,
        DockerAggregate.period_type == period,
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
        metrics_query = metrics_query.where(DockerMetric.container_id == container_id)
    metrics_query = metrics_query.order_by(DockerMetric.collected_at.desc()).limit(limit)

    result = await db.execute(metrics_query)
    return result.scalars().all()


# ─── CSV-экспорт системных метрик ──────────────────────────────────────────

_SYSTEM_RAW_HEADER = ["collected_at", "cpu_percent", "memory_percent", "disk_percent"]
_SYSTEM_AGG_HEADER = [
    "period_start",
    "period_end",
    "avg_cpu",
    "min_cpu",
    "max_cpu",
    "avg_memory",
    "min_memory",
    "max_memory",
    "avg_disk",
    "min_disk",
    "max_disk",
    "sample_count",
]
_EXPORT_LIMITS = {
    "raw": timedelta(hours=24),
    "fivemin": timedelta(days=7),
    "hourly": timedelta(days=30),
    "daily": timedelta(days=365),
}


def _normalize_utc(dt: datetime) -> datetime:
    """Если datetime naive — считаем, что это UTC."""
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt


_GRANULARITY_TO_PERIOD = {
    "fivemin": AggregatePeriodType.fivemin,
    "hourly": AggregatePeriodType.hourly,
    "daily": AggregatePeriodType.daily,
}


def _granularity_to_period(granularity: str) -> AggregatePeriodType:
    """Маппит строку granularity из Query на enum PeriodType."""
    return _GRANULARITY_TO_PERIOD[granularity]


async def _verify_server_ownership(db: AsyncSession, server_id: int, user_id: int) -> Server:
    server = (
        await db.execute(select(Server).where(Server.id == server_id, Server.owner_id == user_id))
    ).scalar_one_or_none()
    if server is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Сервер не найден")
    return server


def _validate_export_range(
    start: datetime, end: datetime, granularity: str
) -> tuple[datetime, datetime]:
    start = _normalize_utc(start)
    end = _normalize_utc(end)
    if end <= start:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="end должен быть позже start"
        )
    max_range = _EXPORT_LIMITS[granularity]
    if (end - start) > max_range:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Период для granularity={granularity} максимум "
                f"{max_range.days or max_range.total_seconds() / 3600:g} "
                f"{'дней' if max_range.days else 'часов'}"
            ),
        )
    return start, end


async def _stream_system_raw(
    db: AsyncSession, server_id: int, start: datetime, end: datetime
) -> AsyncIterator[dict]:
    query = (
        select(Metric)
        .where(
            Metric.server_id == server_id,
            Metric.collected_at >= start,
            Metric.collected_at <= end,
        )
        .order_by(Metric.collected_at)
    )
    result = await db.stream(query)
    async for m in result.scalars():
        yield {
            "collected_at": m.collected_at.isoformat(),
            "cpu_percent": m.cpu_percent,
            "memory_percent": m.memory_percent,
            "disk_percent": m.disk_percent,
        }


async def _stream_system_agg(
    db: AsyncSession,
    server_id: int,
    start: datetime,
    end: datetime,
    period: AggregatePeriodType,
) -> AsyncIterator[dict]:
    query = (
        select(MetricAggregate)
        .where(
            MetricAggregate.server_id == server_id,
            MetricAggregate.period_type == period,
            MetricAggregate.period_start >= start,
            MetricAggregate.period_start <= end,
        )
        .order_by(MetricAggregate.period_start)
    )
    result = await db.stream(query)
    async for a in result.scalars():
        yield {
            "period_start": a.period_start.isoformat(),
            "period_end": a.period_end.isoformat(),
            "avg_cpu": a.avg_cpu,
            "min_cpu": a.min_cpu,
            "max_cpu": a.max_cpu,
            "avg_memory": a.avg_memory,
            "min_memory": a.min_memory,
            "max_memory": a.max_memory,
            "avg_disk": a.avg_disk,
            "min_disk": a.min_disk,
            "max_disk": a.max_disk,
            "sample_count": a.sample_count,
        }


@router.get("/{server_id}/metrics/export")
async def export_system_metrics(
    server_id: int,
    start: datetime = Query(..., description="Начало периода (ISO datetime)"),
    end: datetime = Query(..., description="Конец периода (ISO datetime)"),
    granularity: Literal["raw", "fivemin", "hourly", "daily"] = Query(default="raw"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """CSV-экспорт системных метрик сервера за период."""
    start, end = _validate_export_range(start, end, granularity)
    await _verify_server_ownership(db, server_id, current_user.id)

    if granularity == "raw":
        header = _SYSTEM_RAW_HEADER
        rows = _stream_system_raw(db, server_id, start, end)
    else:
        period = _granularity_to_period(granularity)
        header = _SYSTEM_AGG_HEADER
        rows = _stream_system_agg(db, server_id, start, end, period)

    filename = f"server-{server_id}-system-{granularity}-{start.date()}-{end.date()}.csv"
    return stream_csv(filename=filename, header=header, rows=rows)


# ─── CSV-экспорт docker-метрик ─────────────────────────────────────────────

_DOCKER_RAW_HEADER = [
    "collected_at",
    "container_name",
    "cpu_percent",
    "memory_usage_mb",
    "memory_limit_mb",
]
_DOCKER_AGG_HEADER = [
    "period_start",
    "period_end",
    "container_name",
    "avg_cpu",
    "min_cpu",
    "max_cpu",
    "avg_memory_usage",
    "max_memory_usage",
    "total_rx_bytes",
    "total_tx_bytes",
    "sample_count",
]


async def _stream_docker_raw(
    db: AsyncSession,
    server_id: int,
    start: datetime,
    end: datetime,
    container_name: str | None,
) -> AsyncIterator[dict]:
    query = select(DockerMetric).where(
        DockerMetric.server_id == server_id,
        DockerMetric.collected_at >= start,
        DockerMetric.collected_at <= end,
    )
    if container_name is not None:
        query = query.where(DockerMetric.container_name == container_name)
    query = query.order_by(DockerMetric.collected_at)

    result = await db.stream(query)
    async for m in result.scalars():
        yield {
            "collected_at": m.collected_at.isoformat(),
            "container_name": m.container_name,
            "cpu_percent": m.cpu_percent,
            "memory_usage_mb": m.memory_usage_mb,
            "memory_limit_mb": m.memory_limit_mb,
        }


async def _stream_docker_agg(
    db: AsyncSession,
    server_id: int,
    start: datetime,
    end: datetime,
    period: AggregatePeriodType,
    container_name: str | None,
) -> AsyncIterator[dict]:
    query = select(DockerAggregate).where(
        DockerAggregate.server_id == server_id,
        DockerAggregate.period_type == period,
        DockerAggregate.period_start >= start,
        DockerAggregate.period_start <= end,
    )
    if container_name is not None:
        query = query.where(DockerAggregate.container_name == container_name)
    query = query.order_by(DockerAggregate.period_start, DockerAggregate.container_name)

    result = await db.stream(query)
    async for a in result.scalars():
        yield {
            "period_start": a.period_start.isoformat(),
            "period_end": a.period_end.isoformat(),
            "container_name": a.container_name,
            "avg_cpu": a.avg_cpu,
            "min_cpu": a.min_cpu,
            "max_cpu": a.max_cpu,
            "avg_memory_usage": a.avg_memory_usage,
            "max_memory_usage": a.max_memory_usage,
            "total_rx_bytes": a.total_rx_bytes,
            "total_tx_bytes": a.total_tx_bytes,
            "sample_count": a.sample_count,
        }


@router.get("/{server_id}/docker-metrics/export")
async def export_docker_metrics(
    server_id: int,
    start: datetime = Query(..., description="Начало периода (ISO datetime)"),
    end: datetime = Query(..., description="Конец периода (ISO datetime)"),
    granularity: Literal["raw", "fivemin", "hourly", "daily"] = Query(default="raw"),
    container_name: str | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """CSV-экспорт docker-метрик сервера за период."""
    start, end = _validate_export_range(start, end, granularity)
    await _verify_server_ownership(db, server_id, current_user.id)

    if granularity == "raw":
        header = _DOCKER_RAW_HEADER
        rows = _stream_docker_raw(db, server_id, start, end, container_name)
    else:
        period = _granularity_to_period(granularity)
        header = _DOCKER_AGG_HEADER
        rows = _stream_docker_agg(db, server_id, start, end, period, container_name)

    filename = f"server-{server_id}-docker-{granularity}-{start.date()}-{end.date()}.csv"
    return stream_csv(filename=filename, header=header, rows=rows)
