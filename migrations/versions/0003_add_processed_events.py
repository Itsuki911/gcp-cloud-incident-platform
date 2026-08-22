"""Add processed event history.

Revision ID: 0003_processed_events
Revises: 0002_updated_at
Create Date: 2026-08-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_processed_events"
down_revision: str | Sequence[str] | None = "0002_updated_at"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Event処理履歴を作る
def upgrade() -> None:
    op.create_table(
        "processed_events",
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("ticket_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("first_received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["ticket_id"], ["tickets.id"]),
        sa.PrimaryKeyConstraint("event_id"),
    )
    op.create_index(
        "ix_processed_events_ticket_id",
        "processed_events",
        ["ticket_id"],
        unique=False,
    )


# Event処理履歴を削除する
def downgrade() -> None:
    op.drop_index("ix_processed_events_ticket_id", table_name="processed_events")
    op.drop_table("processed_events")
