"""Review issue and issue-chunk association models per spec §7.4."""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

PRIMARY_KEY = BigInteger().with_variant(Integer, "sqlite")
FOREIGN_KEY = BigInteger().with_variant(Integer, "sqlite")


class ReviewIssue(Base):
    """One audited issue with evidence, per (task, fingerprint)."""

    __tablename__ = "review_issues"
    __table_args__ = (
        UniqueConstraint("task_id", "fingerprint"),
        CheckConstraint(
            "end_line >= start_line",
            name="ck_issues_line_range",
        ),
        CheckConstraint(
            "category <> 'security' OR (cwe_id IS NOT NULL AND cwe_id <> '')",
            name="ck_issues_security_cwe",
        ),
        Index("ix_issues_task", "task_id", "risk_level"),
    )

    id: Mapped[int] = mapped_column(PRIMARY_KEY, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(
        FOREIGN_KEY, ForeignKey("review_tasks.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[int] = mapped_column(
        FOREIGN_KEY, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    category: Mapped[str] = mapped_column(
        String(32), nullable=False
    )  # security / bug / performance / maintainability
    issue_type: Mapped[str] = mapped_column(String(64), nullable=False)
    risk_level: Mapped[str] = mapped_column(
        String(16), nullable=False
    )  # High / Medium / Low
    rule_id: Mapped[str | None] = mapped_column(String(64))
    cwe_id: Mapped[str | None] = mapped_column(String(32))

    relative_path: Mapped[str] = mapped_column(String(512), nullable=False)
    start_line: Mapped[int] = mapped_column(nullable=False)
    end_line: Mapped[int] = mapped_column(nullable=False)
    evidence: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    suggestion: Mapped[str] = mapped_column(Text, nullable=False)
    fixed_example: Mapped[str | None] = mapped_column(Text)

    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    evidence_status: Mapped[str] = mapped_column(String(32), nullable=False)
    critic_decision: Mapped[str | None] = mapped_column(String(32))
    critic_reason: Mapped[str | None] = mapped_column(Text)
    needs_human_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    review_round: Mapped[int] = mapped_column(nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open")

    created_at: Mapped[datetime] = mapped_column(
        nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


class ReviewIssueChunk(Base):
    """Many-to-many link between issues and the chunks used as evidence."""

    __tablename__ = "review_issue_chunks"

    issue_id: Mapped[int] = mapped_column(
        FOREIGN_KEY,
        ForeignKey("review_issues.id", ondelete="CASCADE"),
        primary_key=True,
    )
    chunk_id: Mapped[int] = mapped_column(
        FOREIGN_KEY,
        ForeignKey("code_chunks.id", ondelete="CASCADE"),
        primary_key=True,
    )
