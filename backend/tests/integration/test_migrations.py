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
        "project_files",
        "projects",
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
    assert {index["name"] for index in inspector.get_indexes("projects")} == {"ix_projects_user_id"}
    assert {constraint["name"] for constraint in inspector.get_check_constraints("projects")} == {
        "ck_projects_total_files_nonnegative",
        "ck_projects_total_lines_nonnegative",
        "ck_projects_total_size_nonnegative",
    }

    command.downgrade(config, "base")

    assert inspect(engine).get_table_names() == ["alembic_version"]
    engine.dispose()
