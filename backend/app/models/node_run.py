"""Per-node-run trace record per spec §12.5 and §7.4 node_runs table.

Each NodeRun records one execution of a graph node with its cost and usage
snapshot.  The run_key is a stable SHA-256 identity so that retries of the
same logical call do not double-count costs.
"""

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

PRIMARY_KEY = BigInteger().with_variant(Integer, "sqlite")
FOREIGN_KEY = BigInteger().with_variant(Integer, "sqlite")


class NodeRun(Base):
    """One row per graph-node invocation — idempotent via (task_id, run_key)."""

    __tablename__ = "node_runs"
    __table_args__ = (
        UniqueConstraint("task_id", "run_key"),
        Index("ix_runs_task", "task_id", "node_name"),
        Index("ix_runs_usage", "task_id", "usage_type", "cost_status"),
    )

    id: Mapped[int] = mapped_column(PRIMARY_KEY, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(
        FOREIGN_KEY, ForeignKey("review_tasks.id", ondelete="CASCADE"), nullable=False
    )
    run_key: Mapped[str] = mapped_column(String(128), nullable=False)
    node_name: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    attempt: Mapped[int] = mapped_column(nullable=False, default=1)

    input_summary: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    output_summary: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    # Usage tracking — §12.5
    usage_type: Mapped[str] = mapped_column(
        String(16), nullable=False, default="none"
    )  # none / llm / embedding
    provider: Mapped[str | None] = mapped_column(String(64))
    model_name: Mapped[str | None] = mapped_column(String(128))
    latency_ms: Mapped[int | None] = mapped_column()

    input_tokens: Mapped[int] = mapped_column(nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(nullable=False, default=0)
    input_price_per_million: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    output_price_per_million: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    pricing_currency: Mapped[str | None] = mapped_column(String(8))
    pricing_version: Mapped[str | None] = mapped_column(String(64))
    cost_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="unavailable"
    )  # available / unavailable
    estimated_cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))

    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
