"""add totp fields to users

Revision ID: 743050206199
Revises: 8fee5b79888e
Create Date: 2026-05-11 18:15:49.748057

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "743050206199"
down_revision: str | Sequence[str] | None = "8fee5b79888e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("users", sa.Column("totp_secret", sa.String(length=64), nullable=True))
    op.add_column(
        "users",
        sa.Column(
            "totp_enabled",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("users", "totp_enabled")
    op.drop_column("users", "totp_secret")
