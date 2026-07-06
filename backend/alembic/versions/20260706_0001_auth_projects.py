"""Create user, project, and project-file tables.

Revision ID: 20260706_0001
Revises:
Create Date: 2026-07-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260706_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON_OBJECT = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
PRIMARY_KEY = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
FOREIGN_KEY = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    """Create the complete Module 02 schema with ownership constraints."""
    op.create_table(
        "users",
        sa.Column("id", PRIMARY_KEY, autoincrement=True, nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("username", name="uq_users_username"),
    )
    op.create_table(
        "projects",
        sa.Column("id", PRIMARY_KEY, autoincrement=True, nullable=False),
        sa.Column("user_id", FOREIGN_KEY, nullable=False),
        sa.Column("project_name", sa.String(length=128), nullable=False),
        sa.Column("storage_key", sa.String(length=128), nullable=False),
        sa.Column("main_language", sa.String(length=32), nullable=True),
        sa.Column(
            "language_stats",
            JSON_OBJECT,
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("total_files", sa.Integer(), server_default="0", nullable=False),
        sa.Column("total_lines", sa.Integer(), server_default="0", nullable=False),
        sa.Column("total_size", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default="created",
            nullable=False,
        ),
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
            name="ck_projects_total_files_nonnegative",
        ),
        sa.CheckConstraint(
            "total_lines >= 0",
            name="ck_projects_total_lines_nonnegative",
        ),
        sa.CheckConstraint(
            "total_size >= 0",
            name="ck_projects_total_size_nonnegative",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("storage_key", name="uq_projects_storage_key"),
    )
    op.create_index("ix_projects_user_id", "projects", ["user_id"], unique=False)
    op.create_table(
        "project_files",
        sa.Column("id", PRIMARY_KEY, autoincrement=True, nullable=False),
        sa.Column("project_id", FOREIGN_KEY, nullable=False),
        sa.Column("relative_path", sa.String(length=512), nullable=False),
        sa.Column("content_hash", sa.String(length=128), nullable=True),
        sa.Column("language", sa.String(length=32), nullable=True),
        sa.Column("size", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("line_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "parse_status",
            sa.String(length=32),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("parse_strategy", sa.String(length=32), nullable=True),
        sa.Column("parse_error", sa.Text(), nullable=True),
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
        sa.CheckConstraint("size >= 0", name="ck_project_files_size_nonnegative"),
        sa.CheckConstraint(
            "line_count >= 0",
            name="ck_project_files_line_count_nonnegative",
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            "relative_path",
            name="uq_project_files_project_path",
        ),
    )
    op.create_index(
        "ix_project_files_project_id",
        "project_files",
        ["project_id"],
        unique=False,
    )


def downgrade() -> None:
    """Drop Module 02 tables in reverse dependency order."""
    op.drop_index("ix_project_files_project_id", table_name="project_files")
    op.drop_table("project_files")
    op.drop_index("ix_projects_user_id", table_name="projects")
    op.drop_table("projects")
    op.drop_table("users")
