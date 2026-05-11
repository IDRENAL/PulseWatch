"""Helper для записи в audit_log. Используется из API-handler'ов.

Best-effort: ошибка записи в аудит никогда не должна валить основной запрос.
"""

from typing import Any

from fastapi import Request
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog


def _client_ip(request: Request | None) -> str | None:
    if request is None or request.client is None:
        return None
    return request.client.host


async def record_audit(
    db: AsyncSession,
    *,
    action: str,
    user_id: int | None = None,
    resource_type: str | None = None,
    resource_id: int | None = None,
    request: Request | None = None,
    meta: dict[str, Any] | None = None,
) -> None:
    """Пишет одну строку в audit_log и коммитит. Ошибки логируются и проглатываются."""
    try:
        entry = AuditLog(
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            ip_address=_client_ip(request),
            meta=meta,
        )
        db.add(entry)
        await db.commit()
    except Exception as exc:
        logger.warning("audit record failed: action={} user_id={}: {}", action, user_id, exc)
        try:
            await db.rollback()
        except Exception:
            pass
