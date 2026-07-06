"""Create asynchronous review tasks and durable events.

Revision ID: 20260706_0003
Revises: 20260706_0002
Create Date: 2026-07-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260706_0003"
down_revision: str | None = "20260706_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON_OBJECT = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
PRIMARY_KEY = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
FOREIGN_KEY = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    """Create owner-scoped tasks and append-only SSE event history."""
    op.create_table(
        "review_tasks",
        sa.Column("id", PRIMARY_KEY, autoincrement=True, nullable=False),
        sa.Column("user_id", FOREIGN_KEY, nullable=False),
        sa.Column("project_id", FOREIGN_KEY, nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("celery_task_id", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=32), server_default="pending", nullable=False),
        sa.Column("review_mode", sa.String(length=32), server_default="security", nullable=False),
        sa.Column("current_stage", sa.String(length=64), nullable=True),
        sa.Column("progress", sa.Integer(), server_default="0", nullable=False),
        sa.Column("llm_call_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("input_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("output_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("estimated_cost", sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column(
            "cost_status", sa.String(length=16), server_default="unavailable", nullable=False
        ),
        sa.Column("pricing_summary", JSON_OBJECT, server_default=sa.text("'{}'"), nullable=False),
        sa.Column("cancel_requested", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("fallback_reason", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("progress BETWEEN 0 AND 100", name="ck_review_tasks_progress_range"),
        sa.CheckConstraint("llm_call_count >= 0", name="ck_review_tasks_llm_calls_nonnegative"),
        sa.CheckConstraint("input_tokens >= 0", name="ck_review_tasks_input_tokens_nonnegative"),
        sa.CheckConstraint("output_tokens >= 0", name="ck_review_tasks_output_tokens_nonnegative"),
        sa.CheckConstraint(
            "cost_status IN ('available', 'unavailable', 'partial')",
            name="ck_review_tasks_cost_status",
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "idempotency_key", name="uq_review_tasks_user_idempotency"),
    )
    op.create_index("ix_review_tasks_project_id", "review_tasks", ["project_id"])
    op.create_index("ix_review_tasks_user_id", "review_tasks", ["user_id"])

    op.create_table(
        "task_events",
        sa.Column("id", PRIMARY_KEY, autoincrement=True, nullable=False),
        sa.Column("task_id", FOREIGN_KEY, nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("stage", sa.String(length=64), nullable=True),
        sa.Column("progress", sa.Integer(), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("metadata", JSON_OBJECT, nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "progress IS NULL OR progress BETWEEN 0 AND 100",
            name="ck_task_events_progress_range",
        ),
        sa.ForeignKeyConstraint(["task_id"], ["review_tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_task_events_created_at", "task_events", ["created_at"])
    op.create_index("ix_task_events_task_id_id", "task_events", ["task_id", "id"])


def downgrade() -> None:
    """Drop review task infrastructure."""
    op.drop_index("ix_task_events_task_id_id", table_name="task_events")
    op.drop_index("ix_task_events_created_at", table_name="task_events")
    op.drop_table("task_events")
    op.drop_index("ix_review_tasks_user_id", table_name="review_tasks")
    op.drop_index("ix_review_tasks_project_id", table_name="review_tasks")
    op.drop_table("review_tasks")
