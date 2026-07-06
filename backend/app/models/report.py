"""Review report persistence per spec §7.4."""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    ForeignKey,
    Integer,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

PRIMARY_KEY = BigInteger().with_variant(Integer, "sqlite")
FOREIGN_KEY = BigInteger().with_variant(Integer, "sqlite")


class ReviewReport(Base):
    """One report per task — deterministic stats + LLM summary."""

    __tablename__ = "review_reports"

    id: Mapped[int] = mapped_column(PRIMARY_KEY, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(
        FOREIGN_KEY,
        ForeignKey("review_tasks.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    project_id: Mapped[int] = mapped_column(
        FOREIGN_KEY,
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    summary: Mapped[str | None] = mapped_column(Text)
    report_content: Mapped[str] = mapped_column(Text, nullable=False)
    severity_stats: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    issue_type_stats: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    coverage_summary: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    metrics_summary: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    degradation_summary: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
