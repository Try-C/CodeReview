"""Persisted code chunks, symbols, and confidence-scored relations."""

import json
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import UserDefinedType

from app.core.database import Base
from app.models.base import TimestampMixin

JSON_OBJECT = JSON().with_variant(JSONB(), "postgresql")
PRIMARY_KEY = BigInteger().with_variant(Integer, "sqlite")
FOREIGN_KEY = BigInteger().with_variant(Integer, "sqlite")
SEARCH_VECTOR = Text().with_variant(TSVECTOR(), "postgresql")


class Vector(UserDefinedType[list[float]]):
    """Minimal pgvector column type without coupling domain code to an SDK."""

    cache_ok = True

    def __init__(self, dimensions: int) -> None:
        self.dimensions = dimensions

    def get_col_spec(self, **kw: object) -> str:
        del kw
        return f"VECTOR({self.dimensions})"

    def bind_processor(self, dialect: object) -> Any:
        del dialect

        def process(value: list[float] | None) -> str | None:
            return None if value is None else json.dumps(value, separators=(",", ":"))

        return process

    def result_processor(self, dialect: object, coltype: object) -> Any:
        del dialect, coltype

        def process(value: object) -> list[float] | None:
            if value is None:
                return None
            if isinstance(value, str):
                return [float(item) for item in json.loads(value)]
            if isinstance(value, (list, tuple)):
                return [float(item) for item in value]
            raise ValueError("Invalid pgvector result")

        return process


EMBEDDING = Vector(1024).with_variant(JSON(), "sqlite")


class CodeChunk(TimestampMixin, Base):
    """One source-backed semantic unit with keyword and optional vector indexes."""

    __tablename__ = "code_chunks"
    __table_args__ = (
        CheckConstraint("start_line > 0", name="ck_code_chunks_start_line"),
        CheckConstraint("end_line >= start_line", name="ck_code_chunks_line_range"),
        CheckConstraint(
            "parse_confidence BETWEEN 0 AND 1",
            name="ck_code_chunks_parse_confidence",
        ),
        CheckConstraint(
            "embedding_status IN ('pending', 'ready', 'failed', 'keyword_only')",
            name="ck_code_chunks_embedding_status",
        ),
        CheckConstraint(
            "index_status IN ('pending', 'ready', 'failed')",
            name="ck_code_chunks_index_status",
        ),
        UniqueConstraint(
            "project_id",
            "chunk_fingerprint",
            name="uq_code_chunks_project_fingerprint",
        ),
        Index("ix_code_chunks_project_language", "project_id", "language"),
        Index("ix_code_chunks_project_path", "project_id", "relative_path"),
    )

    id: Mapped[int] = mapped_column(PRIMARY_KEY, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        FOREIGN_KEY, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    file_id: Mapped[int] = mapped_column(
        FOREIGN_KEY, ForeignKey("project_files.id", ondelete="CASCADE"), nullable=False
    )
    relative_path: Mapped[str] = mapped_column(String(512), nullable=False)
    file_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    chunk_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    language: Mapped[str] = mapped_column(String(32), nullable=False)
    symbol_type: Mapped[str | None] = mapped_column(String(64))
    symbol_name: Mapped[str | None] = mapped_column(String(256))
    qualified_name: Mapped[str | None] = mapped_column(String(512))
    parent_symbol: Mapped[str | None] = mapped_column(String(512))
    start_line: Mapped[int] = mapped_column(nullable=False)
    end_line: Mapped[int] = mapped_column(nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    neighbors: Mapped[dict[str, Any]] = mapped_column(
        JSON_OBJECT, nullable=False, default=dict, server_default=text("'{}'")
    )
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON_OBJECT, nullable=False, default=dict, server_default=text("'{}'")
    )
    parser_name: Mapped[str | None] = mapped_column(String(64))
    parser_version: Mapped[str | None] = mapped_column(String(32))
    parse_confidence: Mapped[float] = mapped_column(
        Float, nullable=False, default=1.0, server_default="1.0"
    )
    embedding_model: Mapped[str | None] = mapped_column(String(128))
    embedding_version: Mapped[int] = mapped_column(nullable=False, default=1, server_default="1")
    embedding: Mapped[list[float] | None] = mapped_column(EMBEDDING)
    embedding_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending", server_default="pending"
    )
    embedding_error: Mapped[str | None] = mapped_column(String(128))
    index_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending", server_default="pending"
    )
    search_text: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    search_vector: Mapped[str | None] = mapped_column(SEARCH_VECTOR)


class CodeSymbol(Base):
    """A declared symbol addressable by later retrieval and evidence checks."""

    __tablename__ = "code_symbols"
    __table_args__ = (
        CheckConstraint("start_line > 0", name="ck_code_symbols_start_line"),
        CheckConstraint("end_line >= start_line", name="ck_code_symbols_line_range"),
        UniqueConstraint("project_id", "symbol_hash", name="uq_code_symbols_project_hash"),
        Index("ix_code_symbols_project_name", "project_id", "symbol_name"),
    )

    id: Mapped[int] = mapped_column(PRIMARY_KEY, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        FOREIGN_KEY, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    file_id: Mapped[int] = mapped_column(
        FOREIGN_KEY, ForeignKey("project_files.id", ondelete="CASCADE"), nullable=False
    )
    chunk_id: Mapped[int | None] = mapped_column(
        FOREIGN_KEY, ForeignKey("code_chunks.id", ondelete="SET NULL")
    )
    symbol_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    symbol_name: Mapped[str] = mapped_column(String(256), nullable=False)
    qualified_name: Mapped[str | None] = mapped_column(String(512))
    symbol_type: Mapped[str] = mapped_column(String(64), nullable=False)
    relative_path: Mapped[str] = mapped_column(String(512), nullable=False)
    start_line: Mapped[int] = mapped_column(nullable=False)
    end_line: Mapped[int] = mapped_column(nullable=False)
    visibility: Mapped[str | None] = mapped_column(String(32))
    signature: Mapped[str | None] = mapped_column(String(512))
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON_OBJECT, nullable=False, default=dict, server_default=text("'{}'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


class CodeRelation(Base):
    """A deliberately incomplete, confidence-scored symbol relation."""

    __tablename__ = "code_relations"
    __table_args__ = (
        CheckConstraint("confidence BETWEEN 0 AND 1", name="ck_code_relations_confidence"),
        CheckConstraint(
            "relation_type IN ('call', 'import', 'extend', 'implement', 'reference')",
            name="ck_code_relations_type",
        ),
        CheckConstraint(
            "resolution_status IN ('resolved', 'unresolved', 'external')",
            name="ck_code_relations_resolution_status",
        ),
        UniqueConstraint(
            "project_id",
            "source_symbol_id",
            "target_name",
            "relation_type",
            name="uq_code_relations_identity",
        ),
    )

    id: Mapped[int] = mapped_column(PRIMARY_KEY, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        FOREIGN_KEY, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    source_symbol_id: Mapped[int] = mapped_column(
        FOREIGN_KEY, ForeignKey("code_symbols.id", ondelete="CASCADE"), nullable=False
    )
    target_symbol_id: Mapped[int | None] = mapped_column(
        FOREIGN_KEY, ForeignKey("code_symbols.id", ondelete="SET NULL")
    )
    target_name: Mapped[str] = mapped_column(String(512), nullable=False)
    relation_type: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.5, server_default="0.5"
    )
    resolution_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="unresolved", server_default="unresolved"
    )
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON_OBJECT, nullable=False, default=dict, server_default=text("'{}'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
