"""Trace record for every retrieval operation."""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

PRIMARY_KEY = BigInteger().with_variant(Integer, "sqlite")
FOREIGN_KEY = BigInteger().with_variant(Integer, "sqlite")


class RetrievalRecord(Base):
    """One row per (task, review_item, query_hash, chunk, round) — idempotent."""

    __tablename__ = "retrieval_records"
    __table_args__ = (
        UniqueConstraint(
            "task_id",
            "review_item_key",
            "query_hash",
            "chunk_id",
            "retrieval_round",
            name="uq_retrieval_records_identity",
        ),
        Index("ix_retrieval_records_task_id", "task_id"),
        Index("ix_retrieval_records_query_hash", "task_id", "query_hash"),
    )

    id: Mapped[int] = mapped_column(PRIMARY_KEY, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(
        FOREIGN_KEY, ForeignKey("review_tasks.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[int] = mapped_column(
        FOREIGN_KEY, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    review_item_key: Mapped[str | None] = mapped_column(String(128))
    query_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    query_preview: Mapped[str | None] = mapped_column(String(256))
    chunk_id: Mapped[int | None] = mapped_column(
        FOREIGN_KEY, ForeignKey("code_chunks.id", ondelete="SET NULL")
    )
    vector_rank: Mapped[int | None] = mapped_column()
    keyword_rank: Mapped[int | None] = mapped_column()
    rrf_score: Mapped[float | None] = mapped_column(Float)
    selected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    retrieval_round: Mapped[int] = mapped_column(nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
