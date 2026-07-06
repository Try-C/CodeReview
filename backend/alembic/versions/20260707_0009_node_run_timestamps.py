"""Store node-run timestamps with timezone information.

Revision ID: 20260707_0009
Revises: 20260707_0008
Create Date: 2026-07-06
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260707_0009"
down_revision: str | None = "20260707_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Preserve UTC-aware timestamps written by the workflow worker."""
    if op.get_bind().dialect.name != "postgresql":
        return
    for column_name in ("started_at", "finished_at"):
        op.alter_column(
            "node_runs",
            column_name,
            existing_type=sa.DateTime(),
            type_=sa.DateTime(timezone=True),
            postgresql_using=f"{column_name} AT TIME ZONE 'UTC'",
        )


def downgrade() -> None:
    """Restore timezone-naive node-run timestamps."""
    if op.get_bind().dialect.name != "postgresql":
        return
    for column_name in ("started_at", "finished_at"):
        op.alter_column(
            "node_runs",
            column_name,
            existing_type=sa.DateTime(timezone=True),
            type_=sa.DateTime(),
            postgresql_using=f"{column_name} AT TIME ZONE 'UTC'",
        )
