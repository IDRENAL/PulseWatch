from datetime import datetime

from sqlalchemy import ForeignKey, Index, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Metric(Base):
    __tablename__ = "metrics"

    id: Mapped[int] = mapped_column(primary_key=True)
    server_id: Mapped[int] = mapped_column(ForeignKey("servers.id"))
    cpu_percent: Mapped[float]
    memory_percent: Mapped[float]
    disk_percent: Mapped[float]
    collected_at: Mapped[datetime] = mapped_column(server_default=func.now())

    __table_args__ = (
        Index("ix_metrics_server_id_collected_at", "server_id", "collected_at"),
    )
