from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.models.alert_rule import MetricType, ThresholdOperator

_ALLOWED_CHANNELS = {"telegram", "email"}


def _validate_channels(value: list[str] | None) -> list[str] | None:
    if value is None:
        return None
    cleaned = [v.strip().lower() for v in value]
    invalid = [v for v in cleaned if v not in _ALLOWED_CHANNELS]
    if invalid:
        raise ValueError(f"Допустимые каналы: {sorted(_ALLOWED_CHANNELS)}; получено: {invalid}")
    # Удаляем дубликаты, сохраняя порядок
    return list(dict.fromkeys(cleaned))


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
    notification_channels: list[str] = Field(default_factory=lambda: ["telegram", "email"])

    @field_validator("notification_channels")
    @classmethod
    def _channels_valid(cls, v: list[str]) -> list[str]:
        return _validate_channels(v) or []


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
    notification_channels: list[str] | None = None

    @field_validator("notification_channels")
    @classmethod
    def _channels_valid(cls, v: list[str] | None) -> list[str] | None:
        return _validate_channels(v)


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
    notification_channels: list[str]
    last_triggered_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
