"""Add updated_at to tickets.

Revision ID: 0002_updated_at
Revises: 0001_initial
Create Date: 2026-08-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_updated_at"
down_revision: str | Sequence[str] | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the nullable updated_at column."""
    op.add_column(
        "tickets",
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """Remove the updated_at column."""
    op.drop_column("tickets", "updated_at")
