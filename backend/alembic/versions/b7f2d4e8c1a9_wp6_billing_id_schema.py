"""wp6_billing_id_schema

Revision ID: b7f2d4e8c1a9
Revises: a8f5c3b1e9d2
Create Date: 2026-11-14 19:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7f2d4e8c1a9'
down_revision: Union[str, Sequence[str], None] = 'a8f5c3b1e9d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Apply WP-6.1 Billing ID schema changes."""
    # 1. Add fulfilment tracking columns and sweep index to orders table
    with op.batch_alter_table('orders') as batch_op:
        batch_op.add_column(
            sa.Column('is_fulfilled', sa.Boolean(), server_default=sa.text('0'), nullable=False)
        )
        batch_op.add_column(
            sa.Column('fulfilled_at', sa.DateTime(), nullable=True)
        )
        batch_op.create_index(
            'idx_orders_fulfilment_sweep',
            ['order_status', 'payment_status', 'is_fulfilled'],
            unique=False,
        )

    # 2. Create billing_counters table
    op.create_table(
        'billing_counters',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('sequence_name', sa.String(length=64), nullable=False),
        sa.Column('current_value', sa.BigInteger(), server_default='200', nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('sequence_name', name='uq_billing_counters_sequence_name'),
    )

    # 3. Create billing_ids table
    op.create_table(
        'billing_ids',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('billing_number', sa.String(length=32), nullable=False),
        sa.Column('sequence_number', sa.BigInteger(), nullable=False),
        sa.Column('order_id', sa.Integer(), nullable=False),
        sa.Column('order_item_id', sa.Integer(), nullable=False),
        sa.Column('unit_index', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('product_id', sa.Integer(), nullable=False),
        sa.Column(
            'programme',
            sa.Enum('PLAN_A', 'PLAN_B', 'LEGACY', name='programme'),
            nullable=False,
        ),
        sa.Column('status', sa.String(length=32), server_default='ALLOCATED', nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ['order_id'], ['orders.id'], onupdate='CASCADE', ondelete='RESTRICT'
        ),
        sa.ForeignKeyConstraint(
            ['order_item_id'], ['order_items.id'], onupdate='CASCADE', ondelete='RESTRICT'
        ),
        sa.ForeignKeyConstraint(
            ['user_id'], ['users.id'], onupdate='CASCADE', ondelete='RESTRICT'
        ),
        sa.ForeignKeyConstraint(
            ['product_id'], ['products.id'], onupdate='CASCADE', ondelete='RESTRICT'
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('billing_number', name='uq_billing_ids_number'),
        sa.UniqueConstraint('sequence_number', name='uq_billing_ids_sequence'),
        sa.UniqueConstraint('order_item_id', 'unit_index', name='uq_billing_ids_item_unit'),
    )
    op.create_index('idx_billing_ids_order_id', 'billing_ids', ['order_id'], unique=False)
    op.create_index('idx_billing_ids_user_id', 'billing_ids', ['user_id'], unique=False)
    op.create_index('idx_billing_ids_programme', 'billing_ids', ['programme'], unique=False)

    # 4. Create billing_engine_claims table
    op.create_table(
        'billing_engine_claims',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('billing_id', sa.BigInteger(), nullable=False),
        sa.Column(
            'engine',
            sa.Enum('PLAN_A', 'PLAN_B', 'LEGACY', name='programme'),
            nullable=False,
        ),
        sa.Column('status', sa.String(length=32), server_default='PENDING', nullable=False),
        sa.Column('claimed_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('processed_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ['billing_id'], ['billing_ids.id'], onupdate='CASCADE', ondelete='RESTRICT'
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('billing_id', name='uq_billing_engine_claims_billing_id'),
    )
    op.create_index(
        'idx_billing_engine_claims_engine_status',
        'billing_engine_claims',
        ['engine', 'status'],
        unique=False,
    )

    # 5. Seed initial global counter row safely
    billing_counters = sa.table(
        'billing_counters',
        sa.column('sequence_name', sa.String),
        sa.column('current_value', sa.BigInteger),
    )
    conn = op.get_bind()
    existing = conn.execute(
        sa.text("SELECT id FROM billing_counters WHERE sequence_name = 'GLOBAL_BILLING_ID'")
    ).scalar()
    if not existing:
        op.bulk_insert(
            billing_counters,
            [{'sequence_name': 'GLOBAL_BILLING_ID', 'current_value': 200}],
        )


def downgrade() -> None:
    """Revert WP-6.1 Billing ID schema changes."""
    op.drop_index(
        'idx_billing_engine_claims_engine_status',
        table_name='billing_engine_claims',
    )
    op.drop_table('billing_engine_claims')

    op.drop_index('idx_billing_ids_programme', table_name='billing_ids')
    op.drop_index('idx_billing_ids_user_id', table_name='billing_ids')
    op.drop_index('idx_billing_ids_order_id', table_name='billing_ids')
    op.drop_table('billing_ids')

    op.drop_table('billing_counters')

    with op.batch_alter_table('orders') as batch_op:
        batch_op.drop_index('idx_orders_fulfilment_sweep')
        batch_op.drop_column('fulfilled_at')
        batch_op.drop_column('is_fulfilled')
