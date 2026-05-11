"""add agent_version to servers

Revision ID: 550c021d358e
Revises: bcd650cf69c9
Create Date: 2026-05-11 13:54:35.389082

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "550c021d358e"
down_revision: str | Sequence[str] | None = "bcd650cf69c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("servers", sa.Column("agent_version", sa.String(length=64), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("servers", "agent_version")
