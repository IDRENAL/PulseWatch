from datetime import datetime

from pydantic import BaseModel, ConfigDict


class DockerMetricCreate(BaseModel):
    container_id: str
    container_name: str
    image: str
    status: str
    cpu_percent: float
    memory_usage_mb: float
    memory_limit_mb: float | None = None


class DockerMetricRead(BaseModel):
    id: int
    server_id: int
    container_id: str
    container_name: str
    image: str
    status: str
    cpu_percent: float
    memory_usage_mb: float
    memory_limit_mb: float | None
    collected_at: datetime

    model_config = ConfigDict(from_attributes=True)
