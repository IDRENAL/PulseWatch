"""create_alert_tables

Revision ID: 7c818dce7bd1
Revises: 278c8ed5c4f5
Create Date: 2026-05-04 13:53:36.354638

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# Идентификаторы ревизий, используются Alembic.
revision: str = '7c818dce7bd1'
down_revision: Union[str, Sequence[str], None] = '278c8ed5c4f5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Обновление схемы."""
    # ### команды автогенерированы Alembic — при необходимости скорректируйте! ###
    op.create_table('alert_rules',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('server_id', sa.Integer(), nullable=False),
    sa.Column('owner_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('metric_type', sa.Enum('system', 'docker', name='metrictype'), nullable=False),
    sa.Column('metric_field', sa.String(length=100), nullable=False),
    sa.Column('operator', sa.Enum('gt', 'gte', 'lt', 'lte', 'eq', 'neq', name='thresholdoperator'), nullable=False),
    sa.Column('threshold_value', sa.Float(), nullable=False),
    sa.Column('container_name', sa.String(length=255), nullable=True),
    sa.Column('cooldown_seconds', sa.Integer(), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('last_triggered_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['server_id'], ['servers.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('alert_events',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('rule_id', sa.Integer(), nullable=False),
    sa.Column('server_id', sa.Integer(), nullable=False),
    sa.Column('metric_value', sa.Float(), nullable=False),
    sa.Column('threshold_value', sa.Float(), nullable=False),
    sa.Column('message', sa.String(length=500), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['rule_id'], ['alert_rules.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['server_id'], ['servers.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    # ### конец команд Alembic ###


def downgrade() -> None:
    """Откат схемы."""
    # ### команды автогенерированы Alembic — при необходимости скорректируйте! ###
    op.drop_table('alert_events')
    op.drop_table('alert_rules')
    sa.Enum(name='metrictype').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='thresholdoperator').drop(op.get_bind(), checkfirst=True)
    # ### конец команд Alembic ###
