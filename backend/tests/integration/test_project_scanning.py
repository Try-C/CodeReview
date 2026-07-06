"""Integration coverage for worker-side scanning and durable scan statistics."""

import asyncio
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import Settings
from app.core.database import Base
from app.models import Project, ProjectFile, ReviewTask, TaskEvent, User
from app.scanner import FileFilter, FileScanner, PriorityClassifier
from app.services.progress_service import ProgressService
from app.storage.local import LocalProjectStorage


def test_scan_classification_is_persisted_and_retry_safe(tmp_path: Path) -> None:
    asyncio.run(_scan_scenario(tmp_path))


async def _scan_scenario(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        app_env="test",
        upload_root=tmp_path / "uploads",
    )
    storage = LocalProjectStorage(settings.upload_root)
    storage_key = "a" * 32
    project_root = storage.root / storage_key
    sources = {
        "src/api/auth.py": "def login():\n    return True\n",
        "src/domain/order.py": "class Order:\n    pass\n",
        "tests/test_order.py": "def test_order():\n    assert True\n",
        "src/generated.py": "GENERATED = True\n",
        "README.md": "# unexpected\n",
    }
    for relative_path, content in sources.items():
        target = project_root.joinpath(*relative_path.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    engine = create_async_engine(
        f"sqlite+aiosqlite:///{(tmp_path / 'scanner.sqlite3').as_posix()}",
        poolclass=NullPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    registered_paths = (
        "src/api/auth.py",
        "src/domain/order.py",
        "tests/test_order.py",
        "src/generated.py",
        "src/missing.py",
    )
    async with sessions() as session:
        user = User(username="scanner-user", password_hash="not-used")
        session.add(user)
        await session.flush()
        project = Project(
            user_id=user.id,
            project_name="scanner-project",
            storage_key=storage_key,
        )
        project.files.extend(
            ProjectFile(relative_path=relative_path) for relative_path in registered_paths
        )
        session.add(project)
        await session.flush()
        task = ReviewTask(
            user_id=user.id,
            project_id=project.id,
            idempotency_key="scan-once",
        )
        session.add(task)
        await session.commit()
        task_id = task.id
        project_id = project.id

    scanner = FileScanner(storage, FileFilter(settings), PriorityClassifier())
    service = ProgressService(sessions, scanner=scanner)
    await service.run_task_lifecycle(task_id)
    await service.run_task_lifecycle(task_id)

    async with sessions() as session:
        loaded_project = await session.get(Project, project_id)
        loaded_task = await session.get(ReviewTask, task_id)
        files = list(
            await session.scalars(
                select(ProjectFile)
                .where(ProjectFile.project_id == project_id)
                .order_by(ProjectFile.relative_path)
            )
        )
        events = list(
            await session.scalars(
                select(TaskEvent).where(TaskEvent.task_id == task_id).order_by(TaskEvent.id)
            )
        )

    assert loaded_project is not None
    assert loaded_task is not None
    assert loaded_task.status == "success"
    assert loaded_project.status == "scanned"
    assert loaded_project.main_language == "python"
    assert loaded_project.language_stats == {"python": 3}
    assert loaded_project.total_files == 3
    assert loaded_project.total_lines == 6
    included_size = sum(
        project_root.joinpath(*path.split("/")).stat().st_size
        for path in ("src/api/auth.py", "src/domain/order.py", "tests/test_order.py")
    )
    assert loaded_project.scan_stats == {
        "coverage": {
            "registered_files": 5,
            "discovered_files": 5,
            "included_files": 3,
            "skipped_files": 1,
            "failed_files": 1,
            "included_lines": 6,
            "included_size": included_size,
            "coverage_rate": 0.6,
        },
        "languages": {"python": {"files": 3, "lines": 6, "size": included_size}},
        "priorities": {"high": 1, "medium": 1, "low": 1},
    }
    outcomes = {
        project_file.relative_path: (
            project_file.scan_status,
            project_file.scan_priority,
            project_file.scan_reason,
        )
        for project_file in files
    }
    assert outcomes == {
        "src/api/auth.py": ("included", "high", None),
        "src/domain/order.py": ("included", "medium", None),
        "src/generated.py": ("skipped", None, "GENERATED_FILE"),
        "src/missing.py": ("failed", None, "FILE_MISSING"),
        "tests/test_order.py": ("included", "low", None),
    }
    assert [event.message for event in events] == [
        "Review worker started",
        "Project scan started",
        "Project scan completed",
        "Review task infrastructure pipeline completed",
    ]
    assert events[2].metadata_ == loaded_project.scan_stats

    await engine.dispose()
