"""wp8_plan_b_commission_engine

Revision ID: d2e3f4a5b6c7
Revises: c1e2d3f4a5b6
Create Date: 2026-11-15 12:25:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd2e3f4a5b6c7'
down_revision: Union[str, Sequence[str], None] = 'c1e2d3f4a5b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Apply WP-8 Plan B Commission Engine schema changes."""
    op.create_table(
        'plan_b_commissions',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('commission_type', sa.String(length=16), nullable=False),
        sa.Column('distributor_id', sa.Integer(), nullable=False),
        sa.Column('referee_id', sa.Integer(), nullable=False),
        sa.Column('order_id', sa.Integer(), nullable=False),
        sa.Column('billing_id', sa.BigInteger(), nullable=True),
        sa.Column('gross_amount', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('operational_cost_amount', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('tds_amount', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('net_amount', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('status', sa.String(length=32), server_default='EARNED', nullable=False),
        sa.Column('idempotency_key', sa.String(length=64), nullable=False),
        sa.Column('processed_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['billing_id'], ['billing_ids.id'], onupdate='CASCADE', ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['distributor_id'], ['users.id'], onupdate='CASCADE', ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['order_id'], ['orders.id'], onupdate='CASCADE', ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['referee_id'], ['users.id'], onupdate='CASCADE', ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('idempotency_key', name='uq_plan_b_comm_idempotency'),
    )
    op.create_index('idx_plan_b_comm_distributor_status', 'plan_b_commissions', ['distributor_id', 'status'])
    op.create_index('idx_plan_b_comm_order_id', 'plan_b_commissions', ['order_id'])
    op.create_index('idx_plan_b_comm_billing_id', 'plan_b_commissions', ['billing_id'])


def downgrade() -> None:
    """Revert WP-8 Plan B Commission Engine schema changes."""
    op.drop_index('idx_plan_b_comm_billing_id', table_name='plan_b_commissions')
    op.drop_index('idx_plan_b_comm_order_id', table_name='plan_b_commissions')
    op.drop_index('idx_plan_b_comm_distributor_status', table_name='plan_b_commissions')
    op.drop_table('plan_b_commissions')

