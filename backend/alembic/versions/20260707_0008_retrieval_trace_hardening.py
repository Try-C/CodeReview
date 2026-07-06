"""Harden retrieval trace for empty and degraded attempts.

Revision ID: 20260707_0008
Revises: 20260707_0007
Create Date: 2026-07-06
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260707_0008"
down_revision: str | None = "20260707_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Record degradation and make empty-attempt traces idempotent."""
    op.add_column(
        "retrieval_records",
        sa.Column("degradation_reason", sa.String(length=255), nullable=True),
    )
    op.create_index(
        "uq_retrieval_records_empty_attempt",
        "retrieval_records",
        ["task_id", "review_item_key", "query_hash", "retrieval_round"],
        unique=True,
        postgresql_where=sa.text("chunk_id IS NULL"),
        sqlite_where=sa.text("chunk_id IS NULL"),
    )


def downgrade() -> None:
    """Remove hardened retrieval trace fields."""
    op.drop_index(
        "uq_retrieval_records_empty_attempt",
        table_name="retrieval_records",
    )
    op.drop_column("retrieval_records", "degradation_reason")
