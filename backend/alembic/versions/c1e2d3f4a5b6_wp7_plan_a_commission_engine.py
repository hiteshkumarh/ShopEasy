"""wp7_plan_a_commission_engine

Revision ID: c1e2d3f4a5b6
Revises: b7f2d4e8c1a9
Create Date: 2026-11-15 12:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c1e2d3f4a5b6'
down_revision: Union[str, Sequence[str], None] = 'b7f2d4e8c1a9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Apply WP-7 Plan A Commission Engine schema changes."""
    op.create_table(
        'plan_a_commissions',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('billing_id', sa.BigInteger(), nullable=False),
        sa.Column('order_id', sa.Integer(), nullable=False),
        sa.Column('purchaser_id', sa.Integer(), nullable=False),
        sa.Column('referrer_id', sa.Integer(), nullable=True),
        sa.Column('applied_referral_code', sa.String(length=20), nullable=True),
        sa.Column('gross_amount', sa.Numeric(precision=10, scale=2), server_default='750.00', nullable=False),
        sa.Column('operational_cost_amount', sa.Numeric(precision=10, scale=2), server_default='0.00', nullable=False),
        sa.Column('tds_amount', sa.Numeric(precision=10, scale=2), server_default='0.00', nullable=False),
        sa.Column('net_amount', sa.Numeric(precision=10, scale=2), server_default='0.00', nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('idempotency_key', sa.String(length=64), nullable=False),
        sa.Column('processed_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['billing_id'], ['billing_ids.id'], onupdate='CASCADE', ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['order_id'], ['orders.id'], onupdate='CASCADE', ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['purchaser_id'], ['users.id'], onupdate='CASCADE', ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['referrer_id'], ['users.id'], onupdate='CASCADE', ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('billing_id', name='uq_plan_a_comm_billing_id'),
        sa.UniqueConstraint('idempotency_key', name='uq_plan_a_comm_idempotency'),
    )
    op.create_index('idx_plan_a_comm_referrer_status', 'plan_a_commissions', ['referrer_id', 'status'])
    op.create_index('idx_plan_a_comm_order_id', 'plan_a_commissions', ['order_id'])


def downgrade() -> None:
    """Revert WP-7 Plan A Commission Engine schema changes."""
    op.drop_index('idx_plan_a_comm_order_id', table_name='plan_a_commissions')
    op.drop_index('idx_plan_a_comm_referrer_status', table_name='plan_a_commissions')
    op.drop_table('plan_a_commissions')

