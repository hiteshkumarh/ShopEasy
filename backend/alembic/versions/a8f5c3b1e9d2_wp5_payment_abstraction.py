"""wp5_payment_abstraction

Revision ID: a8f5c3b1e9d2
Revises: 79b742f969d6
Create Date: 2026-11-14 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a8f5c3b1e9d2'
down_revision: Union[str, Sequence[str], None] = '79b742f969d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Apply WP-5 Payment Abstraction additive schema changes."""
    # 1. Create payment_attempts table
    op.create_table(
        'payment_attempts',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('order_id', sa.Integer(), nullable=False),
        sa.Column('attempt_reference', sa.String(length=64), nullable=False),
        sa.Column('provider', sa.String(length=32), nullable=False),
        sa.Column('amount', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('currency', sa.String(length=3), server_default='INR', nullable=False),
        sa.Column(
            'status',
            sa.Enum('pending', 'completed', 'failed', 'simulated_refunded', name='paymentstatus'),
            server_default='pending',
            nullable=False,
        ),
        sa.Column('provider_transaction_id', sa.String(length=128), nullable=True),
        sa.Column('failure_reason', sa.Text(), nullable=True),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ['order_id'], ['orders.id'], onupdate='CASCADE', ondelete='RESTRICT'
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('attempt_reference', name='uq_payment_attempts_reference'),
    )
    op.create_index('idx_payment_attempts_order_id', 'payment_attempts', ['order_id'], unique=False)
    op.create_index(
        'idx_payment_attempts_status_expires',
        'payment_attempts',
        ['status', 'expires_at'],
        unique=False,
    )

    # 2. Create payment_events table (Inbound idempotency and audit journal)
    op.create_table(
        'payment_events',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('provider', sa.String(length=32), nullable=False),
        sa.Column('provider_event_id', sa.String(length=128), nullable=False),
        sa.Column('event_type', sa.String(length=64), nullable=False),
        sa.Column('order_id', sa.Integer(), nullable=True),
        sa.Column('payment_attempt_id', sa.BigInteger(), nullable=True),
        sa.Column('payload_json', sa.Text(), nullable=False),
        sa.Column('status', sa.String(length=32), server_default='RECEIVED', nullable=False),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('processed_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ['order_id'], ['orders.id'], onupdate='CASCADE', ondelete='RESTRICT'
        ),
        sa.ForeignKeyConstraint(
            ['payment_attempt_id'], ['payment_attempts.id'], onupdate='CASCADE', ondelete='RESTRICT'
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('provider', 'provider_event_id', name='uq_payment_events_provider_event_id'),
    )
    op.create_index('idx_payment_events_order_id', 'payment_events', ['order_id'], unique=False)


def downgrade() -> None:
    """Revert WP-5 Payment Abstraction schema changes."""
    op.drop_index('idx_payment_events_order_id', table_name='payment_events')
    op.drop_table('payment_events')

    op.drop_index('idx_payment_attempts_status_expires', table_name='payment_attempts')
    op.drop_index('idx_payment_attempts_order_id', table_name='payment_attempts')
    op.drop_table('payment_attempts')
