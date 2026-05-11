"""add notification_channels to alert_rules

Revision ID: a79e822e0093
Revises: 646f32b63886
Create Date: 2026-05-11 16:46:41.764787

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "a79e822e0093"
down_revision: str | Sequence[str] | None = "646f32b63886"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "alert_rules",
        sa.Column(
            "notification_channels",
            postgresql.ARRAY(sa.String()),
            nullable=False,
            server_default=sa.text("ARRAY['telegram','email']::text[]"),
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("alert_rules", "notification_channels")
