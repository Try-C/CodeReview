"""Persistence model for resumable, owner-scoped folder uploads."""

from typing import TYPE_CHECKING

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin

if TYPE_CHECKING:
    from app.models.project import Project
    from app.models.user import User

JSON_ARRAY = JSON().with_variant(JSONB(), "postgresql")
PRIMARY_KEY = BigInteger().with_variant(Integer, "sqlite")
FOREIGN_KEY = BigInteger().with_variant(Integer, "sqlite")


class UploadSession(TimestampMixin, Base):
    """Tracks an upload manifest and deterministic coverage counters."""

    __tablename__ = "upload_sessions"
    __table_args__ = (
        CheckConstraint("total_files >= 0", name="ck_upload_sessions_total_files_nonnegative"),
        CheckConstraint(
            "uploaded_files >= 0",
            name="ck_upload_sessions_uploaded_files_nonnegative",
        ),
        CheckConstraint(
            "skipped_files >= 0",
            name="ck_upload_sessions_skipped_files_nonnegative",
        ),
        CheckConstraint(
            "failed_files >= 0",
            name="ck_upload_sessions_failed_files_nonnegative",
        ),
        CheckConstraint("total_size >= 0", name="ck_upload_sessions_total_size_nonnegative"),
        CheckConstraint(
            "uploaded_size >= 0",
            name="ck_upload_sessions_uploaded_size_nonnegative",
        ),
        Index("ix_upload_sessions_user_id", "user_id"),
    )

    id: Mapped[int] = mapped_column(PRIMARY_KEY, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        FOREIGN_KEY,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    project_id: Mapped[int | None] = mapped_column(
        FOREIGN_KEY,
        ForeignKey("projects.id", ondelete="SET NULL"),
    )
    upload_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    project_name: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="created",
        server_default="created",
    )
    total_files: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    uploaded_files: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    skipped_files: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    failed_files: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    total_size: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
        server_default="0",
    )
    uploaded_size: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
        server_default="0",
    )
    manifest: Mapped[list[dict[str, object]]] = mapped_column(
        JSON_ARRAY,
        nullable=False,
        default=list,
        server_default=text("'[]'"),
    )
    error_message: Mapped[str | None] = mapped_column(Text)

    user: Mapped["User"] = relationship()
    project: Mapped["Project | None"] = relationship()
