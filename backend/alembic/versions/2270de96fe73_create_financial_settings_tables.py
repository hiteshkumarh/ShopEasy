"""create_financial_settings_tables

Revision ID: 2270de96fe73
Revises: 4bed57dc0ac3
Create Date: 2026-11-14 09:32:38.616241

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2270de96fe73'
down_revision: Union[str, Sequence[str], None] = '4bed57dc0ac3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create versioned financial_settings and financial_settings_history tables."""
    op.create_table(
        'financial_settings',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('programme', sa.Enum('PLAN_A', 'PLAN_B', 'LEGACY', name='programme'), nullable=False),
        sa.Column('setting_key', sa.String(length=64), nullable=False),
        sa.Column('setting_value', sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column('currency', sa.String(length=3), server_default='INR', nullable=False),
        sa.Column('description', sa.String(length=255), nullable=True),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('effective_from', sa.DateTime(), nullable=False),
        sa.Column('effective_to', sa.DateTime(), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default=sa.text('1'), nullable=False),
        sa.Column('created_by_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint('version >= 1', name='chk_fin_settings_version_positive'),
        sa.CheckConstraint('setting_value >= 0.000000', name='chk_fin_settings_value_non_negative'),
        sa.CheckConstraint('effective_to IS NULL OR effective_to >= effective_from', name='chk_fin_settings_effective_window'),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], onupdate='CASCADE', ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('programme', 'setting_key', 'version', name='uq_fin_settings_prog_key_version'),
    )
    op.create_index('ix_fin_settings_lookup', 'financial_settings', ['programme', 'setting_key', 'effective_from', 'effective_to'], unique=False)
    op.create_index('ix_fin_settings_active', 'financial_settings', ['programme', 'setting_key', 'is_active'], unique=False)

    op.create_table(
        'financial_settings_history',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('setting_id', sa.Integer(), nullable=False),
        sa.Column('programme', sa.Enum('PLAN_A', 'PLAN_B', 'LEGACY', name='programme'), nullable=False),
        sa.Column('setting_key', sa.String(length=64), nullable=False),
        sa.Column('old_value', sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column('new_value', sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('action', sa.Enum('CREATED', 'UPDATED', 'DEACTIVATED', 'REACTIVATED', name='settingaction'), nullable=False),
        sa.Column('reason', sa.String(length=255), nullable=True),
        sa.Column('changed_by_id', sa.Integer(), nullable=True),
        sa.Column('changed_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['changed_by_id'], ['users.id'], onupdate='CASCADE', ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['setting_id'], ['financial_settings.id'], onupdate='CASCADE', ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_fin_settings_hist_changed_at', 'financial_settings_history', ['changed_at'], unique=False)
    op.create_index('ix_fin_settings_hist_lookup', 'financial_settings_history', ['programme', 'setting_key'], unique=False)
    op.create_index('ix_fin_settings_hist_setting', 'financial_settings_history', ['setting_id'], unique=False)


def downgrade() -> None:
    """Drop financial_settings_history and financial_settings tables."""
    op.drop_index('ix_fin_settings_hist_setting', table_name='financial_settings_history')
    op.drop_index('ix_fin_settings_hist_lookup', table_name='financial_settings_history')
    op.drop_index('ix_fin_settings_hist_changed_at', table_name='financial_settings_history')
    op.drop_table('financial_settings_history')

    op.drop_index('ix_fin_settings_active', table_name='financial_settings')
    op.drop_index('ix_fin_settings_lookup', table_name='financial_settings')
    op.drop_table('financial_settings')
