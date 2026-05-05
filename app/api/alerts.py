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
    await db.delete(rule)
    await db.commit()


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
