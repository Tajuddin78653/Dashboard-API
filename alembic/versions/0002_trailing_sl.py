"""add trailing_sl and highest_price to trades

Revision ID: 0002_trailing_sl
Revises: 0001
Create Date: 2026-08-27
"""
from alembic import op
import sqlalchemy as sa

revision = "0002_trailing_sl"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("trades", sa.Column("trailing_sl",    sa.Float(), nullable=True))
    op.add_column("trades", sa.Column("highest_price",  sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("trades", "highest_price")
    op.drop_column("trades", "trailing_sl")
