"""Add vector, full-text, symbol, and relation indexing.

Revision ID: 20260706_0005
Revises: 20260706_0004
Create Date: 2026-07-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.types import UserDefinedType

from alembic import op

revision: str = "20260706_0005"
down_revision: str | None = "20260706_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON_OBJECT = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
PRIMARY_KEY = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
FOREIGN_KEY = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


class Vector(UserDefinedType[list[float]]):
    """Migration-local pgvector type fixed at this revision."""

    cache_ok = True

    def __init__(self, dimensions: int) -> None:
        self.dimensions = dimensions

    def get_col_spec(self, **kw: object) -> str:
        del kw
        return f"VECTOR({self.dimensions})"


def upgrade() -> None:
    """Create the Module 07 indexing schema and PostgreSQL indexes."""
    is_postgresql = op.get_bind().dialect.name == "postgresql"
    if is_postgresql:
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    embedding_type = Vector(1024) if is_postgresql else sa.JSON()
    search_vector_type = postgresql.TSVECTOR() if is_postgresql else sa.Text()

    op.create_table(
        "code_chunks",
        sa.Column("id", PRIMARY_KEY, autoincrement=True, nullable=False),
        sa.Column("project_id", FOREIGN_KEY, nullable=False),
        sa.Column("file_id", FOREIGN_KEY, nullable=False),
        sa.Column("relative_path", sa.String(length=512), nullable=False),
        sa.Column("file_hash", sa.String(length=128), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("chunk_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("language", sa.String(length=32), nullable=False),
        sa.Column("symbol_type", sa.String(length=64)),
        sa.Column("symbol_name", sa.String(length=256)),
        sa.Column("qualified_name", sa.String(length=512)),
        sa.Column("parent_symbol", sa.String(length=512)),
        sa.Column("start_line", sa.Integer(), nullable=False),
        sa.Column("end_line", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("neighbors", JSON_OBJECT, server_default=sa.text("'{}'"), nullable=False),
        sa.Column("metadata", JSON_OBJECT, server_default=sa.text("'{}'"), nullable=False),
        sa.Column("parser_name", sa.String(length=64)),
        sa.Column("parser_version", sa.String(length=32)),
        sa.Column("parse_confidence", sa.Float(), server_default="1.0", nullable=False),
        sa.Column("embedding_model", sa.String(length=128)),
        sa.Column("embedding_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("embedding", embedding_type),
        sa.Column(
            "embedding_status",
            sa.String(length=32),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("embedding_error", sa.String(length=128)),
        sa.Column(
            "index_status",
            sa.String(length=32),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("search_text", sa.Text(), server_default="", nullable=False),
        sa.Column("search_vector", search_vector_type),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("start_line > 0", name="ck_code_chunks_start_line"),
        sa.CheckConstraint("end_line >= start_line", name="ck_code_chunks_line_range"),
        sa.CheckConstraint(
            "parse_confidence BETWEEN 0 AND 1",
            name="ck_code_chunks_parse_confidence",
        ),
        sa.CheckConstraint(
            "embedding_status IN ('pending', 'ready', 'failed', 'keyword_only')",
            name="ck_code_chunks_embedding_status",
        ),
        sa.CheckConstraint(
            "index_status IN ('pending', 'ready', 'failed')",
            name="ck_code_chunks_index_status",
        ),
        sa.ForeignKeyConstraint(["file_id"], ["project_files.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            "chunk_fingerprint",
            name="uq_code_chunks_project_fingerprint",
        ),
    )
    op.create_index(
        "ix_code_chunks_project_language",
        "code_chunks",
        ["project_id", "language"],
    )
    op.create_index(
        "ix_code_chunks_project_path",
        "code_chunks",
        ["project_id", "relative_path"],
    )

    op.create_table(
        "code_symbols",
        sa.Column("id", PRIMARY_KEY, autoincrement=True, nullable=False),
        sa.Column("project_id", FOREIGN_KEY, nullable=False),
        sa.Column("file_id", FOREIGN_KEY, nullable=False),
        sa.Column("chunk_id", FOREIGN_KEY),
        sa.Column("symbol_hash", sa.String(length=128), nullable=False),
        sa.Column("symbol_name", sa.String(length=256), nullable=False),
        sa.Column("qualified_name", sa.String(length=512)),
        sa.Column("symbol_type", sa.String(length=64), nullable=False),
        sa.Column("relative_path", sa.String(length=512), nullable=False),
        sa.Column("start_line", sa.Integer(), nullable=False),
        sa.Column("end_line", sa.Integer(), nullable=False),
        sa.Column("visibility", sa.String(length=32)),
        sa.Column("signature", sa.String(length=512)),
        sa.Column("metadata", JSON_OBJECT, server_default=sa.text("'{}'"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("start_line > 0", name="ck_code_symbols_start_line"),
        sa.CheckConstraint("end_line >= start_line", name="ck_code_symbols_line_range"),
        sa.ForeignKeyConstraint(["chunk_id"], ["code_chunks.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["file_id"], ["project_files.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "symbol_hash", name="uq_code_symbols_project_hash"),
    )
    op.create_index(
        "ix_code_symbols_project_name",
        "code_symbols",
        ["project_id", "symbol_name"],
    )

    op.create_table(
        "code_relations",
        sa.Column("id", PRIMARY_KEY, autoincrement=True, nullable=False),
        sa.Column("project_id", FOREIGN_KEY, nullable=False),
        sa.Column("source_symbol_id", FOREIGN_KEY, nullable=False),
        sa.Column("target_symbol_id", FOREIGN_KEY),
        sa.Column("target_name", sa.String(length=512), nullable=False),
        sa.Column("relation_type", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.Float(), server_default="0.5", nullable=False),
        sa.Column(
            "resolution_status",
            sa.String(length=32),
            server_default="unresolved",
            nullable=False,
        ),
        sa.Column("metadata", JSON_OBJECT, server_default=sa.text("'{}'"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("confidence BETWEEN 0 AND 1", name="ck_code_relations_confidence"),
        sa.CheckConstraint(
            "relation_type IN ('call', 'import', 'extend', 'implement', 'reference')",
            name="ck_code_relations_type",
        ),
        sa.CheckConstraint(
            "resolution_status IN ('resolved', 'unresolved', 'external')",
            name="ck_code_relations_resolution_status",
        ),
        sa.ForeignKeyConstraint(["source_symbol_id"], ["code_symbols.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_symbol_id"], ["code_symbols.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            "source_symbol_id",
            "target_name",
            "relation_type",
            name="uq_code_relations_identity",
        ),
    )

    if is_postgresql:
        op.execute(
            """
            CREATE FUNCTION code_chunks_search_vector_update()
            RETURNS TRIGGER AS $$
            BEGIN
                NEW.search_vector :=
                    to_tsvector('simple'::regconfig, COALESCE(NEW.search_text, ''));
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_code_chunks_search_vector
            BEFORE INSERT OR UPDATE OF search_text ON code_chunks
            FOR EACH ROW EXECUTE FUNCTION code_chunks_search_vector_update()
            """
        )
        op.execute(
            "CREATE INDEX ix_code_chunks_vector ON code_chunks "
            "USING hnsw (embedding vector_cosine_ops) WHERE embedding IS NOT NULL"
        )
        op.execute("CREATE INDEX ix_code_chunks_fts ON code_chunks USING gin (search_vector)")


def downgrade() -> None:
    """Drop indexes and tables in reverse dependency order."""
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_code_chunks_fts")
        op.execute("DROP INDEX IF EXISTS ix_code_chunks_vector")
        op.execute("DROP TRIGGER IF EXISTS trg_code_chunks_search_vector ON code_chunks")
        op.execute("DROP FUNCTION IF EXISTS code_chunks_search_vector_update()")
    op.drop_table("code_relations")
    op.drop_index("ix_code_symbols_project_name", table_name="code_symbols")
    op.drop_table("code_symbols")
    op.drop_index("ix_code_chunks_project_path", table_name="code_chunks")
    op.drop_index("ix_code_chunks_project_language", table_name="code_chunks")
    op.drop_table("code_chunks")
