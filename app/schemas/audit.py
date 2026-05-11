from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class AuditLogRead(BaseModel):
    id: int
    user_id: int | None
    action: str
    resource_type: str | None
    resource_id: int | None
    ip_address: str | None
    meta: dict[str, Any] | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
