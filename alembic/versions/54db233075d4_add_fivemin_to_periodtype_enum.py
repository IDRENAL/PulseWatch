"""add fivemin to periodtype enum

Revision ID: 54db233075d4
Revises: b3ee6f8a901f
Create Date: 2026-05-06 15:09:37.470261

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "54db233075d4"
down_revision: str | Sequence[str] | None = "b3ee6f8a901f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Добавляет значение 'fivemin' в ENUM-тип periodtype.

    В Postgres 12+ ALTER TYPE ADD VALUE поддерживает IF NOT EXISTS,
    поэтому миграция идемпотентна.
    """
    op.execute("ALTER TYPE periodtype ADD VALUE IF NOT EXISTS 'fivemin' BEFORE 'hourly'")


def downgrade() -> None:
    """Откат значения из ENUM в Postgres невозможен без полного пересоздания типа.

    Безопасный downgrade требует:
      1) удалить все строки с period_type='fivemin',
      2) пересоздать тип без этого значения.
    Для учебного проекта оставляем no-op — не критично.
    """
    pass
