"""wp3_migration_a_dual_programme_core

Revision ID: 79b742f969d6
Revises: 2270de96fe73
Create Date: 2026-11-14 12:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '79b742f969d6'
down_revision: Union[str, Sequence[str], None] = '2270de96fe73'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Apply WP-3 Migration A additive schema changes."""
    # 1. Add dual-programme and status columns and indexes to users table
    op.add_column(
        'users',
        sa.Column(
            'programme',
            sa.Enum('PLAN_A', 'PLAN_B', 'LEGACY', name='programme'),
            server_default='LEGACY',
            nullable=False,
        ),
    )
    op.add_column(
        'users',
        sa.Column(
            'account_status',
            sa.Enum('ACTIVE', 'BLOCKED', 'DEACTIVATED', name='accountstatus'),
            server_default='ACTIVE',
            nullable=False,
        ),
    )
    op.create_index('idx_users_programme', 'users', ['programme'], unique=False)
    op.create_index('idx_users_account_status', 'users', ['account_status'], unique=False)
    op.create_index('idx_users_prog_role', 'users', ['programme', 'role'], unique=False)

    # 2. Create account_status_history table
    op.create_table(
        'account_status_history',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column(
            'old_status',
            sa.Enum('ACTIVE', 'BLOCKED', 'DEACTIVATED', name='accountstatus'),
            nullable=True,
        ),
        sa.Column(
            'new_status',
            sa.Enum('ACTIVE', 'BLOCKED', 'DEACTIVATED', name='accountstatus'),
            nullable=False,
        ),
        sa.Column('reason', sa.String(length=255), nullable=False),
        sa.Column('changed_by_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(
            ['changed_by_id'], ['users.id'], onupdate='RESTRICT', ondelete='RESTRICT'
        ),
        sa.ForeignKeyConstraint(
            ['user_id'], ['users.id'], onupdate='CASCADE', ondelete='RESTRICT'
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'idx_account_status_hist_user',
        'account_status_history',
        ['user_id', 'created_at'],
        unique=False,
    )
    op.create_index(
        'idx_account_status_hist_changed_by',
        'account_status_history',
        ['changed_by_id'],
        unique=False,
    )

    # 3. Create referral_relationships table
    op.create_table(
        'referral_relationships',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('referee_id', sa.Integer(), nullable=False),
        sa.Column('referrer_id', sa.Integer(), nullable=False),
        sa.Column(
            'referee_programme',
            sa.Enum('PLAN_A', 'PLAN_B', 'LEGACY', name='programme'),
            nullable=False,
        ),
        sa.Column(
            'referrer_programme',
            sa.Enum('PLAN_A', 'PLAN_B', 'LEGACY', name='programme'),
            nullable=False,
        ),
        sa.Column('referral_code_used', sa.String(length=20), nullable=False),
        sa.Column('binding_channel', sa.String(length=30), nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default=sa.text('1'), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint('referee_id != referrer_id', name='chk_ref_rel_no_self'),
        sa.ForeignKeyConstraint(
            ['referee_id'], ['users.id'], onupdate='RESTRICT', ondelete='RESTRICT'
        ),
        sa.ForeignKeyConstraint(
            ['referrer_id'], ['users.id'], onupdate='RESTRICT', ondelete='RESTRICT'
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('referee_id', name='uq_referral_rel_referee'),
    )
    op.create_index(
        'idx_ref_rel_referrer',
        'referral_relationships',
        ['referrer_id', 'is_active'],
        unique=False,
    )
    op.create_index(
        'idx_ref_rel_code',
        'referral_relationships',
        ['referral_code_used'],
        unique=False,
    )

    # 4. Create audit_logs table
    op.create_table(
        'audit_logs',
        sa.Column(
            'id',
            sa.BigInteger().with_variant(sa.Integer(), 'sqlite'),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column('actor_id', sa.Integer(), nullable=True),
        sa.Column('actor_role', sa.String(length=30), nullable=True),
        sa.Column('action', sa.String(length=60), nullable=False),
        sa.Column('entity_type', sa.String(length=50), nullable=False),
        sa.Column('entity_id', sa.String(length=50), nullable=False),
        sa.Column('old_values', sa.Text(), nullable=True),
        sa.Column('new_values', sa.Text(), nullable=True),
        sa.Column('ip_address', sa.String(length=45), nullable=True),
        sa.Column('user_agent', sa.String(length=255), nullable=True),
        sa.Column('metadata_json', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(
            ['actor_id'], ['users.id'], onupdate='RESTRICT', ondelete='RESTRICT'
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'idx_audit_logs_entity', 'audit_logs', ['entity_type', 'entity_id'], unique=False
    )
    op.create_index(
        'idx_audit_logs_actor', 'audit_logs', ['actor_id', 'created_at'], unique=False
    )
    op.create_index(
        'idx_audit_logs_action', 'audit_logs', ['action', 'created_at'], unique=False
    )
    op.create_index('idx_audit_logs_created', 'audit_logs', ['created_at'], unique=False)

    # 5. Create notifications table
    op.create_table(
        'notifications',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column(
            'programme',
            sa.Enum('PLAN_A', 'PLAN_B', 'LEGACY', name='programme'),
            nullable=False,
        ),
        sa.Column('event_type', sa.String(length=60), nullable=False),
        sa.Column('title', sa.String(length=150), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('reference_type', sa.String(length=50), nullable=True),
        sa.Column('reference_id', sa.String(length=50), nullable=True),
        sa.Column('is_read', sa.Boolean(), server_default=sa.text('0'), nullable=False),
        sa.Column('read_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(
            ['user_id'], ['users.id'], onupdate='CASCADE', ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'idx_notifications_user_read',
        'notifications',
        ['user_id', 'is_read', 'created_at'],
        unique=False,
    )
    op.create_index(
        'idx_notifications_user_prog', 'notifications', ['user_id', 'programme'], unique=False
    )


def downgrade() -> None:
    """Revert WP-3 Migration A additive schema changes."""
    # 1. Drop notifications table and indexes
    op.drop_index('idx_notifications_user_prog', table_name='notifications')
    op.drop_index('idx_notifications_user_read', table_name='notifications')
    op.drop_table('notifications')

    # 2. Drop audit_logs table and indexes
    op.drop_index('idx_audit_logs_created', table_name='audit_logs')
    op.drop_index('idx_audit_logs_action', table_name='audit_logs')
    op.drop_index('idx_audit_logs_actor', table_name='audit_logs')
    op.drop_index('idx_audit_logs_entity', table_name='audit_logs')
    op.drop_table('audit_logs')

    # 3. Drop referral_relationships table and indexes
    op.drop_index('idx_ref_rel_code', table_name='referral_relationships')
    op.drop_index('idx_ref_rel_referrer', table_name='referral_relationships')
    op.drop_table('referral_relationships')

    # 4. Drop account_status_history table and indexes
    op.drop_index('idx_account_status_hist_changed_by', table_name='account_status_history')
    op.drop_index('idx_account_status_hist_user', table_name='account_status_history')
    op.drop_table('account_status_history')

    # 5. Drop indexes and columns from users table
    op.drop_index('idx_users_prog_role', table_name='users')
    op.drop_index('idx_users_account_status', table_name='users')
    op.drop_index('idx_users_programme', table_name='users')
    op.drop_column('users', 'account_status')
    op.drop_column('users', 'programme')

