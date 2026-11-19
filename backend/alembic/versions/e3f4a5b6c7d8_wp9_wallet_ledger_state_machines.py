"""wp9_wallet_ledger_state_machines

Revision ID: e3f4a5b6c7d8
Revises: d2e3f4a5b6c7
Create Date: 2026-11-15 12:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e3f4a5b6c7d8'
down_revision: Union[str, Sequence[str], None] = 'd2e3f4a5b6c7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Apply WP-9 Wallet Ledger and Withdrawal state machine schema enhancements."""
    # 1. Add is_frozen flag to wallets table
    op.add_column(
        'wallets',
        sa.Column('is_frozen', sa.Boolean(), server_default='0', nullable=False),
    )

    # 2. Create wallet_freeze_history table
    op.create_table(
        'wallet_freeze_history',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('wallet_id', sa.Integer(), nullable=False),
        sa.Column('admin_id', sa.Integer(), nullable=False),
        sa.Column('action', sa.String(length=16), nullable=False),
        sa.Column('reason', sa.String(length=255), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['admin_id'], ['users.id'], onupdate='CASCADE', ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['wallet_id'], ['wallets.id'], onupdate='CASCADE', ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_wallet_freeze_wallet_id', 'wallet_freeze_history', ['wallet_id'])
    op.create_index('idx_wallet_freeze_admin_id', 'wallet_freeze_history', ['admin_id'])

    # 3. Add state machine and tracking columns to withdrawals table
    op.add_column(
        'withdrawals',
        sa.Column('rejection_reason', sa.String(length=255), nullable=True),
    )
    op.add_column(
        'withdrawals',
        sa.Column('admin_id', sa.Integer(), nullable=True),
    )
    op.add_column(
        'withdrawals',
        sa.Column('receipt_reference', sa.String(length=64), nullable=True),
    )
    # Adjust completed_at to be nullable (as withdrawal starts in REQUESTED/PAYOUT_PENDING)
    op.alter_column('withdrawals', 'completed_at', existing_type=sa.DateTime(), nullable=True)
    # Add foreign key constraint for admin_id
    op.create_foreign_key(
        'fk_withdrawals_admin_user',
        'withdrawals',
        'users',
        ['admin_id'],
        ['id'],
        onupdate='CASCADE',
        ondelete='SET NULL',
    )


def downgrade() -> None:
    """Revert WP-9 schema enhancements."""
    op.drop_constraint('fk_withdrawals_admin_user', 'withdrawals', type_='foreignkey')
    op.alter_column('withdrawals', 'completed_at', existing_type=sa.DateTime(), nullable=False)
    op.drop_column('withdrawals', 'receipt_reference')
    op.drop_column('withdrawals', 'admin_id')
    op.drop_column('withdrawals', 'rejection_reason')

    op.drop_index('idx_wallet_freeze_admin_id', table_name='wallet_freeze_history')
    op.drop_index('idx_wallet_freeze_wallet_id', table_name='wallet_freeze_history')
    op.drop_table('wallet_freeze_history')

    op.drop_column('wallets', 'is_frozen')

