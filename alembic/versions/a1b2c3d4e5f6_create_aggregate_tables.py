"""create_aggregate_tables

Revision ID: a1b2c3d4e5f6
Revises: 7c818dce7bd1
Create Date: 2026-05-04 16:15:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# Идентификаторы ревизий, используются Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: str | Sequence[str] | None = "7c818dce7bd1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Создание таблиц metric_aggregates и docker_aggregates."""
    # Создаём ENUM-тип для period_type
    periodtype = sa.Enum("hourly", "daily", name="periodtype")
    periodtype.create(op.get_bind(), checkfirst=True)

    # Таблица агрегированных системных метрик
    op.create_table(
        "metric_aggregates",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("server_id", sa.Integer(), nullable=False),
        sa.Column("period_type", periodtype, nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("avg_cpu", sa.Float(), nullable=False),
        sa.Column("min_cpu", sa.Float(), nullable=False),
        sa.Column("max_cpu", sa.Float(), nullable=False),
        sa.Column("avg_memory", sa.Float(), nullable=False),
        sa.Column("min_memory", sa.Float(), nullable=False),
        sa.Column("max_memory", sa.Float(), nullable=False),
        sa.Column("avg_disk", sa.Float(), nullable=False),
        sa.Column("min_disk", sa.Float(), nullable=False),
        sa.Column("max_disk", sa.Float(), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["server_id"], ["servers.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "server_id", "period_type", "period_start", name="uq_metric_agg_server_period"
        ),
    )

    # Таблица агрегированных Docker-метрик
    op.create_table(
        "docker_aggregates",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("server_id", sa.Integer(), nullable=False),
        sa.Column("container_name", sa.String(255), nullable=False),
        sa.Column("period_type", periodtype, nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("avg_cpu", sa.Float(), nullable=False),
        sa.Column("min_cpu", sa.Float(), nullable=False),
        sa.Column("max_cpu", sa.Float(), nullable=False),
        sa.Column("avg_memory_usage", sa.Float(), nullable=False),
        sa.Column("max_memory_usage", sa.Float(), nullable=False),
        sa.Column("total_rx_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_tx_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["server_id"], ["servers.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "server_id",
            "container_name",
            "period_type",
            "period_start",
            name="uq_docker_agg_container_period",
        ),
    )


def downgrade() -> None:
    """Удаление таблиц metric_aggregates и docker_aggregates."""
    op.drop_table("docker_aggregates")
    op.drop_table("metric_aggregates")

    # Удаляем ENUM-тип
    periodtype = sa.Enum("hourly", "daily", name="periodtype")
    periodtype.drop(op.get_bind(), checkfirst=True)
