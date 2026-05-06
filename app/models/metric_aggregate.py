from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Integer, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class PeriodType(str, PyEnum):
    fivemin = "fivemin"
    hourly = "hourly"
    daily = "daily"


class MetricAggregate(Base):
    __tablename__ = "metric_aggregates"
    __table_args__ = (
        UniqueConstraint(
            "server_id",
            "period_type",
            "period_start",
            name="uq_metric_agg_server_period",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    server_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("servers.id", ondelete="CASCADE"), nullable=False
    )
    period_type: Mapped[PeriodType] = mapped_column(Enum(PeriodType), nullable=False)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    avg_cpu: Mapped[float] = mapped_column(Float, nullable=False)
    min_cpu: Mapped[float] = mapped_column(Float, nullable=False)
    max_cpu: Mapped[float] = mapped_column(Float, nullable=False)
    avg_memory: Mapped[float] = mapped_column(Float, nullable=False)
    min_memory: Mapped[float] = mapped_column(Float, nullable=False)
    max_memory: Mapped[float] = mapped_column(Float, nullable=False)
    avg_disk: Mapped[float] = mapped_column(Float, nullable=False)
    min_disk: Mapped[float] = mapped_column(Float, nullable=False)
    max_disk: Mapped[float] = mapped_column(Float, nullable=False)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
