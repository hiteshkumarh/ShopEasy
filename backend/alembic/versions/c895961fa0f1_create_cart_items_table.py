"""create_cart_items_table

Revision ID: c895961fa0f1
Revises: 71dba0e1425f
Create Date: 2026-11-04 14:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c895961fa0f1'
down_revision: Union[str, Sequence[str], None] = '71dba0e1425f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create cart_items table for customer cart persistence."""
    op.create_table(
        'cart_items',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('product_id', sa.Integer(), nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['product_id'], ['products.id'], onupdate='CASCADE', ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], onupdate='CASCADE', ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'product_id', name='uq_cart_items_user_product'),
        sa.CheckConstraint('quantity > 0', name='chk_cart_items_quantity_positive'),
    )
    op.create_index('idx_cart_items_user', 'cart_items', ['user_id'], unique=False)


def downgrade() -> None:
    """Drop cart_items table."""
    op.drop_index('idx_cart_items_user', table_name='cart_items')
    op.drop_table('cart_items')

