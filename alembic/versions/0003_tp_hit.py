"""add tp_hit to trades

Revision ID: 0003_tp_hit
Revises: 0002_trailing_sl
Create Date: 2026-08-27
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_tp_hit"
down_revision = "0002_trailing_sl"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("trades", sa.Column("tp_hit", sa.Boolean(), nullable=True, server_default="false"))


def downgrade() -> None:
    op.drop_column("trades", "tp_hit")
