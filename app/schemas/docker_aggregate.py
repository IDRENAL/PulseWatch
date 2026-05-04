from datetime import datetime

from pydantic import BaseModel

from app.models.metric_aggregate import PeriodType


class DockerAggregateRead(BaseModel):
    """Чтение агрегированных Docker-метрик."""
    id: int
    server_id: int
    container_name: str
    period_type: PeriodType
    period_start: datetime
    period_end: datetime
    avg_cpu: float
    min_cpu: float
    max_cpu: float
    avg_memory_usage: float
    max_memory_usage: float
    total_rx_bytes: int
    total_tx_bytes: int
    sample_count: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
