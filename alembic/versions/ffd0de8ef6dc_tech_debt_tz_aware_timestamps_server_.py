"""tech debt: tz-aware timestamps + server_defaults + per-owner unique server name

Revision ID: ffd0de8ef6dc
Revises: 0dcd1bd7f795
Create Date: 2026-05-02 11:16:36.519389

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ffd0de8ef6dc"
down_revision: str | Sequence[str] | None = "0dcd1bd7f795"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # TIMESTAMP -> TIMESTAMPTZ. USING ... AT TIME ZONE 'UTC' трактует существующие
    # значения как UTC независимо от текущего timezone сессии БД.
    op.alter_column(
        "metrics",
        "collected_at",
        existing_type=postgresql.TIMESTAMP(),
        type_=sa.DateTime(timezone=True),
        existing_nullable=False,
        existing_server_default=sa.text("now()"),
        postgresql_using="collected_at AT TIME ZONE 'UTC'",
    )
    op.alter_column(
        "servers",
        "created_at",
        existing_type=postgresql.TIMESTAMP(),
        type_=sa.DateTime(timezone=True),
        existing_nullable=False,
        existing_server_default=sa.text("now()"),
        postgresql_using="created_at AT TIME ZONE 'UTC'",
    )
    op.alter_column(
        "servers",
        "last_seen_at",
        existing_type=postgresql.TIMESTAMP(),
        type_=sa.DateTime(timezone=True),
        existing_nullable=True,
        postgresql_using="last_seen_at AT TIME ZONE 'UTC'",
    )
    op.alter_column(
        "users",
        "created_at",
        existing_type=postgresql.TIMESTAMP(),
        type_=sa.DateTime(timezone=True),
        existing_nullable=False,
        existing_server_default=sa.text("now()"),
        postgresql_using="created_at AT TIME ZONE 'UTC'",
    )

    # server_default для is_active — чтобы raw INSERT не падал на NOT NULL.
    op.alter_column("users", "is_active", server_default=sa.text("true"))
    op.alter_column("servers", "is_active", server_default=sa.text("true"))

    # name больше не глобально уникальный, теперь уникален в рамках owner_id.
    op.drop_constraint(op.f("servers_name_key"), "servers", type_="unique")
    op.create_unique_constraint("uq_servers_owner_id_name", "servers", ["owner_id", "name"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("uq_servers_owner_id_name", "servers", type_="unique")
    op.create_unique_constraint(
        op.f("servers_name_key"),
        "servers",
        ["name"],
        postgresql_nulls_not_distinct=False,
    )

    op.alter_column("servers", "is_active", server_default=None)
    op.alter_column("users", "is_active", server_default=None)

    op.alter_column(
        "users",
        "created_at",
        existing_type=sa.DateTime(timezone=True),
        type_=postgresql.TIMESTAMP(),
        existing_nullable=False,
        existing_server_default=sa.text("now()"),
    )
    op.alter_column(
        "servers",
        "last_seen_at",
        existing_type=sa.DateTime(timezone=True),
        type_=postgresql.TIMESTAMP(),
        existing_nullable=True,
    )
    op.alter_column(
        "servers",
        "created_at",
        existing_type=sa.DateTime(timezone=True),
        type_=postgresql.TIMESTAMP(),
        existing_nullable=False,
        existing_server_default=sa.text("now()"),
    )
    op.alter_column(
        "metrics",
        "collected_at",
        existing_type=sa.DateTime(timezone=True),
        type_=postgresql.TIMESTAMP(),
        existing_nullable=False,
        existing_server_default=sa.text("now()"),
    )
