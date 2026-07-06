"""Add agent workflow tables: review_issues, review_issue_chunks, review_reports, node_runs.

Revision ID: 20260706_0007
Revises: 20260706_0006
Create Date: 2026-07-06
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260707_0007"
down_revision: str | None = "20260706_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PRIMARY_KEY = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
FOREIGN_KEY = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    """Create review_issues, review_issue_chunks, review_reports, node_runs."""
    # ── review_issues ────────────────────────────────────────────────────
    op.create_table(
        "review_issues",
        sa.Column("id", PRIMARY_KEY, autoincrement=True, nullable=False),
        sa.Column("task_id", FOREIGN_KEY, nullable=False),
        sa.Column("project_id", FOREIGN_KEY, nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("title", sa.String(256), nullable=False),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("issue_type", sa.String(64), nullable=False),
        sa.Column("risk_level", sa.String(16), nullable=False),
        sa.Column("rule_id", sa.String(64)),
        sa.Column("cwe_id", sa.String(32)),
        sa.Column("relative_path", sa.String(512), nullable=False),
        sa.Column("start_line", sa.Integer(), nullable=False),
        sa.Column("end_line", sa.Integer(), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("suggestion", sa.Text(), nullable=False),
        sa.Column("fixed_example", sa.Text()),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("evidence_status", sa.String(32), nullable=False),
        sa.Column("critic_decision", sa.String(32)),
        sa.Column("critic_reason", sa.Text()),
        sa.Column("needs_human_review", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("review_round", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(32), nullable=False, server_default="'open'"),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "end_line >= start_line",
            name="ck_issues_line_range",
        ),
        sa.CheckConstraint(
            "category <> 'security' OR (cwe_id IS NOT NULL AND cwe_id <> '')",
            name="ck_issues_security_cwe",
        ),
        sa.ForeignKeyConstraint(["task_id"], ["review_tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id", "fingerprint"),
    )
    op.create_index("ix_issues_task", "review_issues", ["task_id", "risk_level"])

    # ── review_issue_chunks ──────────────────────────────────────────────
    op.create_table(
        "review_issue_chunks",
        sa.Column("issue_id", FOREIGN_KEY, nullable=False),
        sa.Column("chunk_id", FOREIGN_KEY, nullable=False),
        sa.ForeignKeyConstraint(["issue_id"], ["review_issues.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["chunk_id"], ["code_chunks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("issue_id", "chunk_id"),
    )

    # ── review_reports ───────────────────────────────────────────────────
    op.create_table(
        "review_reports",
        sa.Column("id", PRIMARY_KEY, autoincrement=True, nullable=False),
        sa.Column("task_id", FOREIGN_KEY, nullable=False),
        sa.Column("project_id", FOREIGN_KEY, nullable=False),
        sa.Column("summary", sa.Text()),
        sa.Column("report_content", sa.Text(), nullable=False),
        sa.Column("severity_stats", sa.JSON, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("issue_type_stats", sa.JSON, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("coverage_summary", sa.JSON, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("metrics_summary", sa.JSON, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("degradation_summary", sa.JSON, nullable=False, server_default=sa.text("'{}'")),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["task_id"], ["review_tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id"),
    )

    # ── node_runs ────────────────────────────────────────────────────────
    op.create_table(
        "node_runs",
        sa.Column("id", PRIMARY_KEY, autoincrement=True, nullable=False),
        sa.Column("task_id", FOREIGN_KEY, nullable=False),
        sa.Column("run_key", sa.String(128), nullable=False),
        sa.Column("node_name", sa.String(128), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("input_summary", sa.JSON),
        sa.Column("output_summary", sa.JSON),
        sa.Column("usage_type", sa.String(16), nullable=False, server_default="'none'"),
        sa.Column("provider", sa.String(64)),
        sa.Column("model_name", sa.String(128)),
        sa.Column("latency_ms", sa.Integer()),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("input_price_per_million", sa.Numeric(12, 6)),
        sa.Column("output_price_per_million", sa.Numeric(12, 6)),
        sa.Column("pricing_currency", sa.String(8)),
        sa.Column("pricing_version", sa.String(64)),
        sa.Column("cost_status", sa.String(16), nullable=False, server_default="'unavailable'"),
        sa.Column("estimated_cost", sa.Numeric(12, 6)),
        sa.Column("error_code", sa.String(64)),
        sa.Column("error_message", sa.Text()),
        sa.Column("started_at", sa.DateTime()),
        sa.Column("finished_at", sa.DateTime()),
        sa.ForeignKeyConstraint(["task_id"], ["review_tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id", "run_key"),
    )
    op.create_index("ix_runs_task", "node_runs", ["task_id", "node_name"])
    op.create_index("ix_runs_usage", "node_runs", ["task_id", "usage_type", "cost_status"])


def downgrade() -> None:
    """Remove agent workflow support."""
    op.drop_index("ix_runs_usage", table_name="node_runs")
    op.drop_index("ix_runs_task", table_name="node_runs")
    op.drop_table("node_runs")
    op.drop_table("review_reports")
    op.drop_table("review_issue_chunks")
    op.drop_index("ix_issues_task", table_name="review_issues")
    op.drop_table("review_issues")
