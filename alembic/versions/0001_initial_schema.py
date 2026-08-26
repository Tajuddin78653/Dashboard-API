"""initial schema

Revision ID: 0001
Revises: 
Create Date: 2025-01-01 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'users',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('email', sa.String(255), nullable=False),
        sa.Column('hashed_password', sa.String(255), nullable=False),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('role', sa.String(20), nullable=False, server_default='viewer'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('email'),
    )
    op.create_index('ix_users_email', 'users', ['email'])

    op.create_table(
        'strategies',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('description', sa.String(500), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )

    op.create_table(
        'signals',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('signal_id', sa.String(30), nullable=False),
        sa.Column('strategy_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('symbol', sa.String(30), nullable=False),
        sa.Column('signal_type', sa.String(10), nullable=False),
        sa.Column('entry_price', sa.Float(), nullable=True),
        sa.Column('timestamp', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('status', sa.String(20), nullable=False, server_default='pending'),
        sa.Column('raw_payload', postgresql.JSON(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('signal_id'),
        sa.ForeignKeyConstraint(['strategy_id'], ['strategies.id'], ondelete='SET NULL'),
    )
    op.create_index('ix_signals_signal_id', 'signals', ['signal_id'])
    op.create_index('ix_signals_symbol', 'signals', ['symbol'])
    op.create_index('ix_signals_timestamp', 'signals', ['timestamp'])

    op.create_table(
        'trades',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('trade_id', sa.String(30), nullable=False),
        sa.Column('signal_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('strategy_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('symbol', sa.String(30), nullable=False),
        sa.Column('signal_type', sa.String(10), nullable=False, server_default='BUY'),
        sa.Column('entry_price', sa.Float(), nullable=False),
        sa.Column('exit_price', sa.Float(), nullable=True),
        sa.Column('stop_loss', sa.Float(), nullable=False),
        sa.Column('target_price', sa.Float(), nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.Column('gross_pnl', sa.Float(), nullable=True),
        sa.Column('charges', sa.Float(), nullable=True),
        sa.Column('net_pnl', sa.Float(), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='entered'),
        sa.Column('reason', sa.String(100), nullable=True),
        sa.Column('entry_time', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('exit_time', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('trade_id'),
        sa.ForeignKeyConstraint(['signal_id'], ['signals.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['strategy_id'], ['strategies.id'], ondelete='SET NULL'),
    )
    op.create_index('ix_trades_trade_id', 'trades', ['trade_id'])
    op.create_index('ix_trades_symbol', 'trades', ['symbol'])

    op.create_table(
        'audit_logs',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('action', sa.String(50), nullable=False),
        sa.Column('details', sa.String(500), nullable=True),
        sa.Column('ip_address', sa.String(45), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
    )
    op.create_index('ix_audit_logs_action', 'audit_logs', ['action'])
    op.create_index('ix_audit_logs_created_at', 'audit_logs', ['created_at'])


def downgrade() -> None:
    op.drop_table('audit_logs')
    op.drop_table('trades')
    op.drop_table('signals')
    op.drop_table('strategies')
    op.drop_table('users')
