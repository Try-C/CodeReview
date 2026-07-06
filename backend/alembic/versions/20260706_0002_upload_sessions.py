"""Create upload session tracking.

Revision ID: 20260706_0002
Revises: 20260706_0001
Create Date: 2026-07-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260706_0002"
down_revision: str | None = "20260706_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON_ARRAY = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
PRIMARY_KEY = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
FOREIGN_KEY = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    """Create owner-scoped upload sessions with coverage counters."""
    op.create_table(
        "upload_sessions",
        sa.Column("id", PRIMARY_KEY, autoincrement=True, nullable=False),
        sa.Column("user_id", FOREIGN_KEY, nullable=False),
        sa.Column("project_id", FOREIGN_KEY, nullable=True),
        sa.Column("upload_id", sa.String(length=128), nullable=False),
        sa.Column("project_name", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="created", nullable=False),
        sa.Column("total_files", sa.Integer(), server_default="0", nullable=False),
        sa.Column("uploaded_files", sa.Integer(), server_default="0", nullable=False),
        sa.Column("skipped_files", sa.Integer(), server_default="0", nullable=False),
        sa.Column("failed_files", sa.Integer(), server_default="0", nullable=False),
        sa.Column("total_size", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("uploaded_size", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("manifest", JSON_ARRAY, server_default=sa.text("'[]'"), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "total_files >= 0",
            name="ck_upload_sessions_total_files_nonnegative",
        ),
        sa.CheckConstraint(
            "uploaded_files >= 0",
            name="ck_upload_sessions_uploaded_files_nonnegative",
        ),
        sa.CheckConstraint(
            "skipped_files >= 0",
            name="ck_upload_sessions_skipped_files_nonnegative",
        ),
        sa.CheckConstraint(
            "failed_files >= 0",
            name="ck_upload_sessions_failed_files_nonnegative",
        ),
        sa.CheckConstraint(
            "total_size >= 0",
            name="ck_upload_sessions_total_size_nonnegative",
        ),
        sa.CheckConstraint(
            "uploaded_size >= 0",
            name="ck_upload_sessions_uploaded_size_nonnegative",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("upload_id", name="uq_upload_sessions_upload_id"),
    )
    op.create_index(
        "ix_upload_sessions_user_id",
        "upload_sessions",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    """Drop upload session tracking."""
    op.drop_index("ix_upload_sessions_user_id", table_name="upload_sessions")
    op.drop_table("upload_sessions")
