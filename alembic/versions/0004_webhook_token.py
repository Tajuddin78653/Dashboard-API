"""add webhook_token to strategies

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-28

Adds a unique webhook_token (UUID string) column to the strategies table.
Immediately seeds tokens for the two Chartink webhook strategies so the
secure /webhook/chartink/{token} route works right after migration.
"""

import uuid
from alembic import op
import sqlalchemy as sa


revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add nullable column
    op.add_column(
        "strategies",
        sa.Column("webhook_token", sa.String(36), unique=True, nullable=True),
    )

    # 2. Seed tokens for the two Chartink webhook strategies
    conn = op.get_bind()

    token1 = str(uuid.uuid4())
    conn.execute(
        sa.text(
            "UPDATE strategies SET webhook_token = :token "
            "WHERE name = 'Chartink Webhook' AND webhook_token IS NULL"
        ),
        {"token": token1},
    )

    token2 = str(uuid.uuid4())
    conn.execute(
        sa.text(
            "UPDATE strategies SET webhook_token = :token "
            "WHERE name = 'Chartink Webhook 2' AND webhook_token IS NULL"
        ),
        {"token": token2},
    )


def downgrade() -> None:
    op.drop_column("strategies", "webhook_token")
