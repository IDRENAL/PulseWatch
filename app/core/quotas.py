"""Лимиты ресурсов по тарифу юзера.

Использование:
    from app.core.quotas import enforce_server_quota, enforce_rule_quota

    await enforce_server_quota(db, user)  # бросает 402 если превышено

Тариф — строковое поле `users.subscription_tier`. Если значение не в TIER_LIMITS,
используется TIER_LIMITS["free"] (безопасный дефолт).
"""

from dataclasses import dataclass

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.alert_rule import AlertRule
from app.models.server import Server
from app.models.user import User


@dataclass(frozen=True)
class TierLimits:
    max_servers: int  # -1 = unlimited
    max_rules: int


TIER_LIMITS: dict[str, TierLimits] = {
    "free": TierLimits(max_servers=3, max_rules=10),
    "pro": TierLimits(max_servers=20, max_rules=100),
    "enterprise": TierLimits(max_servers=-1, max_rules=-1),
}


def get_limits(tier: str) -> TierLimits:
    return TIER_LIMITS.get(tier, TIER_LIMITS["free"])


async def enforce_server_quota(db: AsyncSession, user: User) -> None:
    """Проверяет, что юзер не превысил лимит серверов своего тарифа.

    Если превысил — HTTP 402 Payment Required (стандартный «оплати тариф» код).
    """
    limits = get_limits(user.subscription_tier)
    if limits.max_servers < 0:
        return  # unlimited

    current = await db.scalar(
        select(func.count()).select_from(Server).where(Server.owner_id == user.id)
    )
    if (current or 0) >= limits.max_servers:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=(
                f"Тариф {user.subscription_tier!r} позволяет максимум "
                f"{limits.max_servers} серверов. Обнови тариф или удали лишние."
            ),
        )


async def enforce_rule_quota(db: AsyncSession, user: User) -> None:
    """Проверяет лимит алерт-правил. Правила считаются у всех серверов юзера
    суммарно, не на сервер.
    """
    limits = get_limits(user.subscription_tier)
    if limits.max_rules < 0:
        return

    # COUNT через JOIN — правила привязаны к серверам, а не напрямую к юзеру
    stmt = (
        select(func.count())
        .select_from(AlertRule)
        .join(Server, AlertRule.server_id == Server.id)
        .where(Server.owner_id == user.id)
    )
    current = await db.scalar(stmt)
    if (current or 0) >= limits.max_rules:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=(
                f"Тариф {user.subscription_tier!r} позволяет максимум "
                f"{limits.max_rules} правил. Обнови тариф или удали лишние."
            ),
        )
