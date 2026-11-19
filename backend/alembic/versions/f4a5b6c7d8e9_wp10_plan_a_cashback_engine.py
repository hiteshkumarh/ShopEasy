"""wp10_plan_a_cashback_engine

Revision ID: f4a5b6c7d8e9
Revises: e3f4a5b6c7d8
Create Date: 2026-11-15 14:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f4a5b6c7d8e9'
down_revision: Union[str, Sequence[str], None] = 'e3f4a5b6c7d8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Apply WP-10 Plan A Cashback Engine additive schema."""
    # 1. plan_a_cashback_queues: Isolated independent FIFO queues (BR-A2)
    op.create_table(
        'plan_a_cashback_queues',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('root_user_id', sa.Integer(), nullable=False),
        sa.Column('active_cycle_id', sa.BigInteger(), nullable=True),
        sa.Column('last_allocated_position', sa.Integer(), server_default='0', nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['root_user_id'], ['users.id'], onupdate='CASCADE', ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('root_user_id', name='uq_plan_a_cb_queue_root_user'),
    )
    op.create_index('idx_plan_a_cb_queue_active_cycle', 'plan_a_cashback_queues', ['active_cycle_id'])

    # 2. plan_a_cashback_entries: Monotonic queue entry per eligible Billing ID (BR-A1, BR-A3)
    op.create_table(
        'plan_a_cashback_entries',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('queue_id', sa.BigInteger(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('billing_id', sa.BigInteger(), nullable=False),
        sa.Column('queue_position', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=32), server_default='WAITING', nullable=False),
        sa.Column('enrolled_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('activated_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['queue_id'], ['plan_a_cashback_queues.id'], onupdate='CASCADE', ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], onupdate='CASCADE', ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['billing_id'], ['billing_ids.id'], onupdate='CASCADE', ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('billing_id', name='uq_plan_a_cb_entry_billing_id'),
        sa.UniqueConstraint('queue_id', 'queue_position', name='uq_plan_a_cb_entry_queue_pos'),
    )
    op.create_index('idx_plan_a_cb_entry_user_status', 'plan_a_cashback_entries', ['user_id', 'status'])
    op.create_index('idx_plan_a_cb_entry_queue_status', 'plan_a_cashback_entries', ['queue_id', 'status'])

    # 3. plan_a_cashback_cycles: 16-contribution (₹4,000) earning cycles (PA-09, PA-10)
    op.create_table(
        'plan_a_cashback_cycles',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('queue_id', sa.BigInteger(), nullable=False),
        sa.Column('queue_entry_id', sa.BigInteger(), nullable=False),
        sa.Column('recipient_user_id', sa.Integer(), nullable=False),
        sa.Column('recipient_billing_id', sa.BigInteger(), nullable=False),
        sa.Column('cycle_number', sa.Integer(), server_default='1', nullable=False),
        sa.Column('completed_contributions', sa.Integer(), server_default='0', nullable=False),
        sa.Column('total_earned', sa.Numeric(precision=10, scale=2), server_default='0.00', nullable=False),
        sa.Column('status', sa.String(length=32), server_default='ACTIVE', nullable=False),
        sa.Column('started_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['queue_id'], ['plan_a_cashback_queues.id'], onupdate='CASCADE', ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['queue_entry_id'], ['plan_a_cashback_entries.id'], onupdate='CASCADE', ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['recipient_user_id'], ['users.id'], onupdate='CASCADE', ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['recipient_billing_id'], ['billing_ids.id'], onupdate='CASCADE', ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('queue_entry_id', name='uq_plan_a_cb_cycle_queue_entry'),
        sa.CheckConstraint('completed_contributions >= 0 AND completed_contributions <= 16', name='chk_plan_a_cb_cycle_contributions'),
        sa.CheckConstraint('total_earned >= 0.00 AND total_earned <= 4000.00', name='chk_plan_a_cb_cycle_total_earned'),
    )
    op.create_index('idx_plan_a_cb_cycle_recipient_status', 'plan_a_cashback_cycles', ['recipient_user_id', 'status'])
    op.create_index('idx_plan_a_cb_cycle_queue_status', 'plan_a_cashback_cycles', ['queue_id', 'status'])

    # 4. plan_a_cashback_contributions: Audit ledger of individual ₹250 contributions (BR-A1, BR-A3)
    op.create_table(
        'plan_a_cashback_contributions',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('queue_id', sa.BigInteger(), nullable=False),
        sa.Column('cycle_id', sa.BigInteger(), nullable=True),
        sa.Column('contributing_billing_id', sa.BigInteger(), nullable=False),
        sa.Column('contributing_user_id', sa.Integer(), nullable=False),
        sa.Column('recipient_user_id', sa.Integer(), nullable=True),
        sa.Column('amount', sa.Numeric(precision=10, scale=2), server_default='250.00', nullable=False),
        sa.Column('status', sa.String(length=32), server_default='ALLOCATED', nullable=False),
        sa.Column('idempotency_key', sa.String(length=64), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['queue_id'], ['plan_a_cashback_queues.id'], onupdate='CASCADE', ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['cycle_id'], ['plan_a_cashback_cycles.id'], onupdate='CASCADE', ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['contributing_billing_id'], ['billing_ids.id'], onupdate='CASCADE', ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['contributing_user_id'], ['users.id'], onupdate='CASCADE', ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['recipient_user_id'], ['users.id'], onupdate='CASCADE', ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('contributing_billing_id', name='uq_plan_a_cb_contrib_billing_id'),
        sa.UniqueConstraint('idempotency_key', name='uq_plan_a_cb_contrib_idempotency'),
    )
    op.create_index('idx_plan_a_cb_contrib_cycle', 'plan_a_cashback_contributions', ['cycle_id'])
    op.create_index('idx_plan_a_cb_contrib_queue_user', 'plan_a_cashback_contributions', ['queue_id', 'contributing_user_id'])

    # 5. plan_a_unallocated_cashback_reserves: Permanent company-owned reserve (BR-A4 Option A & BR-A5 Option A)
    op.create_table(
        'plan_a_unallocated_cashback_reserves',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('queue_id', sa.BigInteger(), nullable=False),
        sa.Column('billing_id', sa.BigInteger(), nullable=False),
        sa.Column('customer_id', sa.Integer(), nullable=False),
        sa.Column('amount', sa.Numeric(precision=10, scale=2), server_default='250.00', nullable=False),
        sa.Column('status', sa.String(length=64), server_default='UNALLOCATED — COMPANY OWNED', nullable=False),
        sa.Column('idempotency_key', sa.String(length=64), nullable=False),
        sa.Column('reserved_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['queue_id'], ['plan_a_cashback_queues.id'], onupdate='CASCADE', ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['billing_id'], ['billing_ids.id'], onupdate='CASCADE', ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['customer_id'], ['users.id'], onupdate='CASCADE', ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('billing_id', name='uq_plan_a_cb_res_billing_id'),
        sa.UniqueConstraint('idempotency_key', name='uq_plan_a_cb_res_idempotency'),
    )
    op.create_index('idx_plan_a_cb_res_queue', 'plan_a_unallocated_cashback_reserves', ['queue_id'])
    op.create_index('idx_plan_a_cb_res_customer', 'plan_a_unallocated_cashback_reserves', ['customer_id'])


def downgrade() -> None:
    """Revert WP-10 Plan A Cashback Engine additive schema."""
    op.drop_index('idx_plan_a_cb_res_customer', table_name='plan_a_unallocated_cashback_reserves')
    op.drop_index('idx_plan_a_cb_res_queue', table_name='plan_a_unallocated_cashback_reserves')
    op.drop_table('plan_a_unallocated_cashback_reserves')

    op.drop_index('idx_plan_a_cb_contrib_queue_user', table_name='plan_a_cashback_contributions')
    op.drop_index('idx_plan_a_cb_contrib_cycle', table_name='plan_a_cashback_contributions')
    op.drop_table('plan_a_cashback_contributions')

    op.drop_index('idx_plan_a_cb_cycle_queue_status', table_name='plan_a_cashback_cycles')
    op.drop_index('idx_plan_a_cb_cycle_recipient_status', table_name='plan_a_cashback_cycles')
    op.drop_table('plan_a_cashback_cycles')

    op.drop_index('idx_plan_a_cb_entry_queue_status', table_name='plan_a_cashback_entries')
    op.drop_index('idx_plan_a_cb_entry_user_status', table_name='plan_a_cashback_entries')
    op.drop_table('plan_a_cashback_entries')

    op.drop_index('idx_plan_a_cb_queue_active_cycle', table_name='plan_a_cashback_queues')
    op.drop_table('plan_a_cashback_queues')

