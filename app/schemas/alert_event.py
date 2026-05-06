from datetime import datetime

from pydantic import BaseModel


class AlertEventRead(BaseModel):
    """Чтение события алерта."""

    id: int
    rule_id: int
    server_id: int
    metric_value: float
    threshold_value: float
    message: str
    container_name: str | None = None
    created_at: datetime
    resolved_at: datetime | None = None

    model_config = {"from_attributes": True}
