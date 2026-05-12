from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.database import get_db
from app.models.alert_event import AlertEvent
from app.models.alert_rule import AlertRule
from app.models.server import Server
from app.models.user import User
from app.schemas.alert_event import AlertEventRead
from app.schemas.alert_rule import AlertRuleCreate, AlertRuleRead, AlertRuleUpdate
from app.services.audit import record_audit
from app.utils.csv_export import stream_csv

router = APIRouter()


async def _verify_server_owner(server_id: int, user: User, db: AsyncSession) -> Server:
    """Проверяет что сервер существует и принадлежит пользователю."""
    server = (
        await db.execute(select(Server).where(Server.id == server_id, Server.owner_id == user.id))
    ).scalar_one_or_none()
    if server is None:
        raise HTTPException(status_code=404, detail="Server not found")
    return server


# 1. POST /alerts/rules — создать правило
@router.post("/rules", response_model=AlertRuleRead, status_code=status.HTTP_201_CREATED)
async def create_alert_rule(
    data: AlertRuleCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _verify_server_owner(data.server_id, current_user, db)
    rule = AlertRule(
        server_id=data.server_id,
        owner_id=current_user.id,
        name=data.name,
        metric_type=data.metric_type,
        metric_field=data.metric_field,
        operator=data.operator,
        threshold_value=data.threshold_value,
        container_name=data.container_name,
        cooldown_seconds=data.cooldown_seconds,
        is_active=data.is_active,
    )
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    await record_audit(
        db,
        action="rule_create",
        user_id=current_user.id,
        resource_type="rule",
        resource_id=rule.id,
    )
    return rule


# 2. GET /alerts/rules — список правил пользователя (с опциональным фильтром по server_id)
@router.get("/rules", response_model=list[AlertRuleRead])
async def list_alert_rules(
    server_id: int | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(AlertRule).where(AlertRule.owner_id == current_user.id)
    if server_id is not None:
        query = query.where(AlertRule.server_id == server_id)
    query = query.order_by(AlertRule.created_at.desc())
    result = await db.execute(query)
    return result.scalars().all()


# 3. GET /alerts/rules/{rule_id} — получить конкретное правило
@router.get("/rules/{rule_id}", response_model=AlertRuleRead)
async def get_alert_rule(
    rule_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rule = (
        await db.execute(
            select(AlertRule).where(AlertRule.id == rule_id, AlertRule.owner_id == current_user.id)
        )
    ).scalar_one_or_none()
    if rule is None:
        raise HTTPException(status_code=404, detail="Alert rule not found")
    return rule


# 4. PATCH /alerts/rules/{rule_id} — обновить правило
@router.patch("/rules/{rule_id}", response_model=AlertRuleRead)
async def update_alert_rule(
    rule_id: int,
    data: AlertRuleUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rule = (
        await db.execute(
            select(AlertRule).where(AlertRule.id == rule_id, AlertRule.owner_id == current_user.id)
        )
    ).scalar_one_or_none()
    if rule is None:
        raise HTTPException(status_code=404, detail="Alert rule not found")

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(rule, field, value)

    await db.commit()
    await db.refresh(rule)
    await record_audit(
        db,
        action="rule_update",
        user_id=current_user.id,
        resource_type="rule",
        resource_id=rule.id,
        meta={"fields": list(update_data.keys())},
    )
    return rule


# 5. DELETE /alerts/rules/{rule_id} — удалить правило
@router.delete("/rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_alert_rule(
    rule_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rule = (
        await db.execute(
            select(AlertRule).where(AlertRule.id == rule_id, AlertRule.owner_id == current_user.id)
        )
    ).scalar_one_or_none()
    if rule is None:
        raise HTTPException(status_code=404, detail="Alert rule not found")
    rule_id_audit = rule.id
    await db.delete(rule)
    await db.commit()
    await record_audit(
        db,
        action="rule_delete",
        user_id=current_user.id,
        resource_type="rule",
        resource_id=rule_id_audit,
    )


# 6. GET /alerts/events — список событий (с фильтрами по server_id, rule_id)
@router.get("/events", response_model=list[AlertEventRead])
async def list_alert_events(
    server_id: int | None = Query(default=None),
    rule_id: int | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = (
        select(AlertEvent)
        .join(AlertRule, AlertEvent.rule_id == AlertRule.id)
        .where(AlertRule.owner_id == current_user.id)
    )
    if server_id is not None:
        query = query.where(AlertEvent.server_id == server_id)
    if rule_id is not None:
        query = query.where(AlertEvent.rule_id == rule_id)
    query = query.order_by(AlertEvent.created_at.desc()).limit(limit)
    result = await db.execute(query)
    return result.scalars().all()


# 7. GET /alerts/events/{event_id} — конкретное событие
@router.get("/events/{event_id}", response_model=AlertEventRead)
async def get_alert_event(
    event_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    event = (
        await db.execute(
            select(AlertEvent)
            .join(AlertRule, AlertEvent.rule_id == AlertRule.id)
            .where(AlertEvent.id == event_id, AlertRule.owner_id == current_user.id)
        )
    ).scalar_one_or_none()
    if event is None:
        raise HTTPException(status_code=404, detail="Alert event not found")
    return event


# 8. GET /alerts/events/export — CSV-экспорт событий
@router.get("/events/export")
async def export_alert_events(
    start: datetime | None = Query(default=None, description="нижняя граница created_at (ISO)"),
    end: datetime | None = Query(default=None, description="верхняя граница created_at (ISO)"),
    server_id: int | None = Query(default=None),
    rule_id: int | None = Query(default=None),
    only_open: bool = Query(
        default=False, description="только нерезолвнутые (resolved_at is null)"
    ),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """CSV-экспорт событий. Период до 90 дней. Default — последние 7 дней."""
    if end is None:
        end = datetime.now(UTC)
    if start is None:
        start = end - timedelta(days=7)
    if (end - start) > timedelta(days=90):
        raise HTTPException(status_code=400, detail="Период не должен превышать 90 дней")

    query = (
        select(AlertEvent, AlertRule.name, Server.name)
        .join(AlertRule, AlertEvent.rule_id == AlertRule.id)
        .join(Server, AlertEvent.server_id == Server.id)
        .where(
            AlertRule.owner_id == current_user.id,
            AlertEvent.created_at >= start,
            AlertEvent.created_at <= end,
        )
        .order_by(AlertEvent.created_at.asc())
    )
    if server_id is not None:
        query = query.where(AlertEvent.server_id == server_id)
    if rule_id is not None:
        query = query.where(AlertEvent.rule_id == rule_id)
    if only_open:
        query = query.where(AlertEvent.resolved_at.is_(None))

    result = await db.execute(query)
    rows = result.tuples().all()

    async def rows_iter() -> AsyncIterator[dict]:
        for event, rule_name, server_name in rows:
            yield {
                "id": event.id,
                "server_id": event.server_id,
                "server_name": server_name,
                "rule_id": event.rule_id,
                "rule_name": rule_name,
                "container_name": event.container_name or "",
                "metric_value": event.metric_value,
                "threshold_value": event.threshold_value,
                "status": "resolved" if event.resolved_at else "open",
                "created_at": event.created_at.isoformat(),
                "resolved_at": event.resolved_at.isoformat() if event.resolved_at else "",
                "message": event.message,
            }

    filename = f"alert_events_{start.date()}_{end.date()}.csv"
    header = [
        "id",
        "server_id",
        "server_name",
        "rule_id",
        "rule_name",
        "container_name",
        "metric_value",
        "threshold_value",
        "status",
        "created_at",
        "resolved_at",
        "message",
    ]
    return stream_csv(filename, header, rows_iter())
