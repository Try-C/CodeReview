"""Migration acceptance tests for the current database schema."""

from pathlib import Path

from alembic.config import Config
from sqlalchemy import create_engine, inspect

from alembic import command


def test_initial_migration_upgrades_and_downgrades(tmp_path: Path) -> None:
    backend_root = Path(__file__).resolve().parents[2]
    database_path = tmp_path / "migration.sqlite3"
    async_url = f"sqlite+aiosqlite:///{database_path.as_posix()}"
    config = Config(backend_root / "alembic.ini")
    config.set_main_option("script_location", str(backend_root / "alembic"))
    config.set_main_option("sqlalchemy.url", async_url)

    command.upgrade(config, "head")
    command.check(config)

    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    inspector = inspect(engine)
    assert set(inspector.get_table_names()) == {
        "alembic_version",
        "code_chunks",
        "code_relations",
        "code_symbols",
        "node_runs",
        "project_files",
        "projects",
        "retrieval_records",
        "review_issue_chunks",
        "review_issues",
        "review_reports",
        "review_tasks",
        "task_events",
        "upload_sessions",
        "users",
    }
    assert inspector.get_foreign_keys("projects")[0]["options"]["ondelete"] == "CASCADE"
    assert inspector.get_foreign_keys("project_files")[0]["options"]["ondelete"] == "CASCADE"
    upload_foreign_keys = {
        foreign_key["referred_table"]: foreign_key["options"]["ondelete"]
        for foreign_key in inspector.get_foreign_keys("upload_sessions")
    }
    assert upload_foreign_keys == {"projects": "SET NULL", "users": "CASCADE"}
    task_foreign_keys = {
        foreign_key["referred_table"]: foreign_key["options"]["ondelete"]
        for foreign_key in inspector.get_foreign_keys("review_tasks")
    }
    assert task_foreign_keys == {"projects": "CASCADE", "users": "CASCADE"}
    assert inspector.get_foreign_keys("task_events")[0]["options"]["ondelete"] == "CASCADE"
    assert {column["name"] for column in inspector.get_columns("task_events")} >= {
        "id",
        "task_id",
        "metadata",
    }
    assert {column["name"] for column in inspector.get_columns("projects")} >= {
        "scan_stats",
    }
    assert {column["name"] for column in inspector.get_columns("project_files")} >= {
        "scan_status",
        "scan_priority",
        "scan_reason",
    }
    assert {column["name"] for column in inspector.get_columns("code_chunks")} >= {
        "chunk_fingerprint",
        "content_hash",
        "embedding",
        "embedding_error",
        "search_text",
        "search_vector",
    }
    assert {index["name"] for index in inspector.get_indexes("code_chunks")} == {
        "ix_code_chunks_project_language",
        "ix_code_chunks_project_path",
    }
    assert {index["name"] for index in inspector.get_indexes("projects")} == {"ix_projects_user_id"}
    assert {constraint["name"] for constraint in inspector.get_check_constraints("projects")} == {
        "ck_projects_total_files_nonnegative",
        "ck_projects_total_lines_nonnegative",
        "ck_projects_total_size_nonnegative",
    }
    assert {column["name"] for column in inspector.get_columns("retrieval_records")} >= {
        "task_id",
        "project_id",
        "query_hash",
        "query_preview",
        "chunk_id",
        "vector_rank",
        "keyword_rank",
        "rrf_score",
        "selected",
        "degradation_reason",
        "retrieval_round",
    }
    assert {index["name"] for index in inspector.get_indexes("retrieval_records")} == {
        "ix_retrieval_records_task_id",
        "ix_retrieval_records_query_hash",
        "uq_retrieval_records_empty_attempt",
    }
    retrieval_record_unique = inspector.get_unique_constraints("retrieval_records")
    assert any(
        set(constraint["column_names"])
        == {
            "task_id",
            "review_item_key",
            "query_hash",
            "chunk_id",
            "retrieval_round",
        }
        for constraint in retrieval_record_unique
    ), "retrieval_records must have an idempotency unique constraint"

    command.downgrade(config, "base")

    assert inspect(engine).get_table_names() == ["alembic_version"]
    engine.dispose()
