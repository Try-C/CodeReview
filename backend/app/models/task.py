"""Review-task and durable progress-event persistence models."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin

JSON_OBJECT = JSON().with_variant(JSONB(), "postgresql")
PRIMARY_KEY = BigInteger().with_variant(Integer, "sqlite")
FOREIGN_KEY = BigInteger().with_variant(Integer, "sqlite")


class ReviewTask(TimestampMixin, Base):
    """One owner-scoped, idempotently-created asynchronous review."""

    __tablename__ = "review_tasks"
    __table_args__ = (
        CheckConstraint("progress BETWEEN 0 AND 100", name="ck_review_tasks_progress_range"),
        CheckConstraint("llm_call_count >= 0", name="ck_review_tasks_llm_calls_nonnegative"),
        CheckConstraint("input_tokens >= 0", name="ck_review_tasks_input_tokens_nonnegative"),
        CheckConstraint("output_tokens >= 0", name="ck_review_tasks_output_tokens_nonnegative"),
        CheckConstraint(
            "cost_status IN ('available', 'unavailable', 'partial')",
            name="ck_review_tasks_cost_status",
        ),
        UniqueConstraint("user_id", "idempotency_key", name="uq_review_tasks_user_idempotency"),
        Index("ix_review_tasks_user_id", "user_id"),
        Index("ix_review_tasks_project_id", "project_id"),
    )

    id: Mapped[int] = mapped_column(PRIMARY_KEY, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        FOREIGN_KEY,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    project_id: Mapped[int] = mapped_column(
        FOREIGN_KEY,
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    celery_task_id: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending", server_default="pending"
    )
    review_mode: Mapped[str] = mapped_column(
        String(32), nullable=False, default="security", server_default="security"
    )
    current_stage: Mapped[str | None] = mapped_column(String(64))
    progress: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    llm_call_count: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    input_tokens: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    output_tokens: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    estimated_cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    cost_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="unavailable", server_default="unavailable"
    )
    pricing_summary: Mapped[dict[str, object]] = mapped_column(
        JSON_OBJECT, nullable=False, default=dict, server_default=text("'{}'")
    )
    cancel_requested: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    fallback_reason: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    events: Mapped[list["TaskEvent"]] = relationship(
        back_populates="task",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="TaskEvent.id",
    )


class TaskEvent(Base):
    """An append-only event whose primary key is the public SSE event ID."""

    __tablename__ = "task_events"
    __table_args__ = (
        CheckConstraint(
            "progress IS NULL OR progress BETWEEN 0 AND 100",
            name="ck_task_events_progress_range",
        ),
        Index("ix_task_events_task_id_id", "task_id", "id"),
        Index("ix_task_events_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(PRIMARY_KEY, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(
        FOREIGN_KEY,
        ForeignKey("review_tasks.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    stage: Mapped[str | None] = mapped_column(String(64))
    progress: Mapped[int | None] = mapped_column()
    message: Mapped[str | None] = mapped_column(Text)
    metadata_: Mapped[dict[str, object] | None] = mapped_column("metadata", JSON_OBJECT)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )

    task: Mapped[ReviewTask] = relationship(back_populates="events")
