"""cascade delete metrics and docker_metrics on server delete

Revision ID: bcd650cf69c9
Revises: 971107cbe3a8
Create Date: 2026-05-11 11:32:15.944932

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "bcd650cf69c9"
down_revision: str | Sequence[str] | None = "971107cbe3a8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_constraint("metrics_server_id_fkey", "metrics", type_="foreignkey")
    op.create_foreign_key(
        "metrics_server_id_fkey",
        "metrics",
        "servers",
        ["server_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_constraint("docker_metrics_server_id_fkey", "docker_metrics", type_="foreignkey")
    op.create_foreign_key(
        "docker_metrics_server_id_fkey",
        "docker_metrics",
        "servers",
        ["server_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("docker_metrics_server_id_fkey", "docker_metrics", type_="foreignkey")
    op.create_foreign_key(
        "docker_metrics_server_id_fkey",
        "docker_metrics",
        "servers",
        ["server_id"],
        ["id"],
    )
    op.drop_constraint("metrics_server_id_fkey", "metrics", type_="foreignkey")
    op.create_foreign_key(
        "metrics_server_id_fkey",
        "metrics",
        "servers",
        ["server_id"],
        ["id"],
    )
