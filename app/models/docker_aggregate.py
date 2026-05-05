from datetime import datetime

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.metric_aggregate import PeriodType


class DockerAggregate(Base):
    __tablename__ = "docker_aggregates"
    __table_args__ = (
        UniqueConstraint(
            "server_id",
            "container_name",
            "period_type",
            "period_start",
            name="uq_docker_agg_container_period",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    server_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("servers.id", ondelete="CASCADE"), nullable=False
    )
    container_name: Mapped[str] = mapped_column(String(255), nullable=False)
    period_type: Mapped[PeriodType] = mapped_column(Enum(PeriodType), nullable=False)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    avg_cpu: Mapped[float] = mapped_column(Float, nullable=False)
    min_cpu: Mapped[float] = mapped_column(Float, nullable=False)
    max_cpu: Mapped[float] = mapped_column(Float, nullable=False)
    avg_memory_usage: Mapped[float] = mapped_column(Float, nullable=False)
    max_memory_usage: Mapped[float] = mapped_column(Float, nullable=False)
    total_rx_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_tx_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
