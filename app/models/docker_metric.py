from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class DockerMetric(Base):
    __tablename__ = "docker_metrics"

    id: Mapped[int] = mapped_column(primary_key=True)
    server_id: Mapped[int] = mapped_column(ForeignKey("servers.id"))
    container_id: Mapped[str]
    container_name: Mapped[str]
    image: Mapped[str]
    status: Mapped[str]
    cpu_percent: Mapped[float]
    memory_usage_mb: Mapped[float]
    memory_limit_mb: Mapped[float | None]
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index(
            "ix_docker_metrics_server_id_collected_at",
            "server_id",
            "collected_at",
        ),
    )
