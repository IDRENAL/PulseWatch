from datetime import datetime

from pydantic import BaseModel, ConfigDict


class MetricCreate(BaseModel):
    cpu_percent: float
    memory_percent: float
    disk_percent: float


class MetricRead(BaseModel):
    id: int
    server_id: int
    cpu_percent: float
    memory_percent: float
    disk_percent: float
    collected_at: datetime

    model_config = ConfigDict(from_attributes=True)
