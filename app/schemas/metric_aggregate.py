from datetime import datetime

from pydantic import BaseModel

from app.models.metric_aggregate import PeriodType


class MetricAggregateRead(BaseModel):
    """Чтение агрегированных системных метрик."""
    id: int
    server_id: int
    period_type: PeriodType
    period_start: datetime
    period_end: datetime
    avg_cpu: float
    min_cpu: float
    max_cpu: float
    avg_memory: float
    min_memory: float
    max_memory: float
    avg_disk: float
    min_disk: float
    max_disk: float
    sample_count: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
