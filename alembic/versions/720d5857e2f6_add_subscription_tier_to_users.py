"""add subscription_tier to users

Revision ID: 720d5857e2f6
Revises: 95fa57d46079
Create Date: 2026-05-12 11:12:57.967022

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "720d5857e2f6"
down_revision: str | Sequence[str] | None = "95fa57d46079"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "users",
        sa.Column(
            "subscription_tier",
            sa.String(length=32),
            nullable=False,
            server_default="free",
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("users", "subscription_tier")
