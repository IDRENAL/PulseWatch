from datetime import datetime

from pydantic import BaseModel, Field

from app.models.alert_rule import MetricType, ThresholdOperator


class AlertRuleCreate(BaseModel):
    """Создание правила алерта."""

    server_id: int
    name: str = Field(..., min_length=1, max_length=255)
    metric_type: MetricType
    metric_field: str = Field(..., min_length=1, max_length=100)
    operator: ThresholdOperator
    threshold_value: float
    container_name: str | None = None  # только для docker metric_type
    cooldown_seconds: int = Field(default=300, ge=0)
    is_active: bool = True


class AlertRuleUpdate(BaseModel):
    """Обновление правила алерта (все поля опциональны)."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    metric_type: MetricType | None = None
    metric_field: str | None = Field(default=None, min_length=1, max_length=100)
    operator: ThresholdOperator | None = None
    threshold_value: float | None = None
    container_name: str | None = None
    cooldown_seconds: int | None = Field(default=None, ge=0)
    is_active: bool | None = None


class AlertRuleRead(BaseModel):
    """Чтение правила алерта."""

    id: int
    server_id: int
    owner_id: int
    name: str
    metric_type: MetricType
    metric_field: str
    operator: ThresholdOperator
    threshold_value: float
    container_name: str | None
    cooldown_seconds: int
    is_active: bool
    last_triggered_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
