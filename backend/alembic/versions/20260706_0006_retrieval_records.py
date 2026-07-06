"""Add retrieval trace records for every hybrid search.

Revision ID: 20260706_0006
Revises: 20260706_0005
Create Date: 2026-07-06
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260706_0006"
down_revision: str | None = "20260706_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PRIMARY_KEY = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
FOREIGN_KEY = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    """Create the retrieval trace table."""
    op.create_table(
        "retrieval_records",
        sa.Column("id", PRIMARY_KEY, autoincrement=True, nullable=False),
        sa.Column("task_id", FOREIGN_KEY, nullable=False),
        sa.Column("project_id", FOREIGN_KEY, nullable=False),
        sa.Column("review_item_key", sa.String(length=128)),
        sa.Column("query_hash", sa.String(length=64), nullable=False),
        sa.Column("query_preview", sa.String(length=256)),
        sa.Column("chunk_id", FOREIGN_KEY),
        sa.Column("vector_rank", sa.Integer()),
        sa.Column("keyword_rank", sa.Integer()),
        sa.Column("rrf_score", sa.Float()),
        sa.Column("selected", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("retrieval_round", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["chunk_id"], ["code_chunks.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["review_tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "task_id",
            "review_item_key",
            "query_hash",
            "chunk_id",
            "retrieval_round",
            name="uq_retrieval_records_identity",
        ),
    )
    op.create_index(
        "ix_retrieval_records_task_id",
        "retrieval_records",
        ["task_id"],
    )
    op.create_index(
        "ix_retrieval_records_query_hash",
        "retrieval_records",
        ["task_id", "query_hash"],
    )


def downgrade() -> None:
    """Remove retrieval trace support."""
    op.drop_index("ix_retrieval_records_query_hash", table_name="retrieval_records")
    op.drop_index("ix_retrieval_records_task_id", table_name="retrieval_records")
    op.drop_table("retrieval_records")
