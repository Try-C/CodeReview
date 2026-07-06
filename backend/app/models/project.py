"""Project and project-file persistence models."""

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
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin

if TYPE_CHECKING:
    from app.models.user import User

JSON_OBJECT = JSON().with_variant(JSONB(), "postgresql")
PRIMARY_KEY = BigInteger().with_variant(Integer, "sqlite")


class Project(TimestampMixin, Base):
    """A user-owned codebase and its deterministic aggregate statistics."""

    __tablename__ = "projects"
    __table_args__ = (
        CheckConstraint("total_files >= 0", name="ck_projects_total_files_nonnegative"),
        CheckConstraint("total_lines >= 0", name="ck_projects_total_lines_nonnegative"),
        CheckConstraint("total_size >= 0", name="ck_projects_total_size_nonnegative"),
        Index("ix_projects_user_id", "user_id"),
    )

    id: Mapped[int] = mapped_column(PRIMARY_KEY, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    project_name: Mapped[str] = mapped_column(String(128), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    main_language: Mapped[str | None] = mapped_column(String(32))
    language_stats: Mapped[dict[str, int]] = mapped_column(
        JSON_OBJECT,
        nullable=False,
        default=dict,
        server_default=text("'{}'"),
    )
    total_files: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    total_lines: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    total_size: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
        server_default="0",
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="created",
        server_default="created",
    )

    owner: Mapped["User"] = relationship(back_populates="projects")
    files: Mapped[list["ProjectFile"]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ProjectFile.relative_path",
    )


class ProjectFile(TimestampMixin, Base):
    """Metadata for one file registered beneath a project root."""

    __tablename__ = "project_files"
    __table_args__ = (
        CheckConstraint("size >= 0", name="ck_project_files_size_nonnegative"),
        CheckConstraint("line_count >= 0", name="ck_project_files_line_count_nonnegative"),
        UniqueConstraint(
            "project_id",
            "relative_path",
            name="uq_project_files_project_path",
        ),
        Index("ix_project_files_project_id", "project_id"),
    )

    id: Mapped[int] = mapped_column(PRIMARY_KEY, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    relative_path: Mapped[str] = mapped_column(String(512), nullable=False)
    content_hash: Mapped[str | None] = mapped_column(String(128))
    language: Mapped[str | None] = mapped_column(String(32))
    size: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    line_count: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    parse_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="pending",
        server_default="pending",
    )
    parse_strategy: Mapped[str | None] = mapped_column(String(32))
    parse_error: Mapped[str | None] = mapped_column(Text)

    project: Mapped[Project] = relationship(back_populates="files")
