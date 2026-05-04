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
    created_at: datetime

    model_config = {"from_attributes": True}
