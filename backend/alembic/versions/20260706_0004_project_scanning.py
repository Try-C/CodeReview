"""Persist deterministic project scan classifications and coverage.

Revision ID: 20260706_0004
Revises: 20260706_0003
Create Date: 2026-07-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260706_0004"
down_revision: str | None = "20260706_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON_OBJECT = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    """Add retry-safe scan state to projects and registered files."""
    op.add_column(
        "projects",
        sa.Column(
            "scan_stats",
            JSON_OBJECT,
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
    )
    op.add_column(
        "project_files",
        sa.Column(
            "scan_status",
            sa.String(length=32),
            server_default="pending",
            nullable=False,
        ),
    )
    op.add_column(
        "project_files",
        sa.Column("scan_priority", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "project_files",
        sa.Column("scan_reason", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    """Remove project scan state in reverse dependency order."""
    op.drop_column("project_files", "scan_reason")
    op.drop_column("project_files", "scan_priority")
    op.drop_column("project_files", "scan_status")
    op.drop_column("projects", "scan_stats")
