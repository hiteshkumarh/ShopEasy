"""expand_otp_code_to_varchar_64

Revision ID: 71dba0e1425f
Revises: ed2396d847bc
Create Date: 2026-11-04 12:58:34.057006

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision: str = '71dba0e1425f'
down_revision: Union[str, Sequence[str], None] = 'ed2396d847bc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: invalidate existing plaintext OTP records and expand otp_code column."""
    # Invalidate existing plaintext OTP records to prevent acceptance of unhashed OTPs
    op.execute(sa.text("UPDATE otps SET is_used = 1 WHERE is_used = 0"))

    op.alter_column('otps', 'otp_code',
               existing_type=mysql.VARCHAR(length=10),
               type_=sa.String(length=64),
               existing_nullable=False)


def downgrade() -> None:
    """Downgrade schema: invalidate records and revert otp_code column."""
    op.execute(sa.text("UPDATE otps SET is_used = 1 WHERE is_used = 0"))

    op.alter_column('otps', 'otp_code',
               existing_type=sa.String(length=64),
               type_=mysql.VARCHAR(length=10),
               existing_nullable=False)
