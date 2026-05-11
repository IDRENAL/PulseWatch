"""add paused to servers

Revision ID: 646f32b63886
Revises: 550c021d358e
Create Date: 2026-05-11 16:04:59.575416

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "646f32b63886"
down_revision: str | Sequence[str] | None = "550c021d358e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "servers",
        sa.Column("paused", sa.Boolean(), nullable=False, server_default="false"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("servers", "paused")
