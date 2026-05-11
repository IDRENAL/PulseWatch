"""add logs table

Revision ID: 8fee5b79888e
Revises: a79e822e0093
Create Date: 2026-05-11 17:34:19.986212

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "8fee5b79888e"
down_revision: str | Sequence[str] | None = "a79e822e0093"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "logs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "server_id",
            sa.Integer(),
            sa.ForeignKey("servers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_logs_server_id_created_at",
        "logs",
        ["server_id", "created_at"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_logs_server_id_created_at", table_name="logs")
    op.drop_table("logs")
