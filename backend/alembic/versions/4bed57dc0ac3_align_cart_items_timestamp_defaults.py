"""align_cart_items_timestamp_defaults

Revision ID: 4bed57dc0ac3
Revises: c895961fa0f1
Create Date: 2026-11-13 17:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4bed57dc0ac3'
down_revision: Union[str, Sequence[str], None] = 'c895961fa0f1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Align cart_items created_at and updated_at server defaults with ORM model metadata.

    Removes the database-level ON UPDATE CURRENT_TIMESTAMP clause on updated_at,
    aligning with the standard server_default=now() and Python-side onupdate=func.now()
    pattern used across all models in the application.
    """
    op.alter_column(
        'cart_items',
        'created_at',
        existing_type=sa.DateTime(),
        server_default=sa.text('now()'),
        existing_nullable=False,
    )
    op.alter_column(
        'cart_items',
        'updated_at',
        existing_type=sa.DateTime(),
        server_default=sa.text('now()'),
        existing_nullable=False,
    )


def downgrade() -> None:
    """Revert cart_items created_at and updated_at server defaults to previous definitions."""
    op.alter_column(
        'cart_items',
        'updated_at',
        existing_type=sa.DateTime(),
        server_default=sa.text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP'),
        existing_nullable=False,
    )
    op.alter_column(
        'cart_items',
        'created_at',
        existing_type=sa.DateTime(),
        server_default=sa.text('CURRENT_TIMESTAMP'),
        existing_nullable=False,
    )
