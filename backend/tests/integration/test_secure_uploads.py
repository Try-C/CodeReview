"""Integration tests for secure manifest-driven project uploads."""

import asyncio
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.core.config import Settings
from app.core.database import Base
from app.core.runtime import RuntimeContext
from app.main import create_app
from app.models import Project
from app.storage.local import LocalProjectStorage
from tests.fakes import FakeHealthDependency


@dataclass(frozen=True, slots=True)
class UploadHarness:
    engine: AsyncEngine
    sessions: async_sessionmaker[AsyncSession]
    storage: LocalProjectStorage


async def _create_schema(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


@pytest.fixture
def upload_harness(tmp_path: Path) -> Iterator[UploadHarness]:
    database_path = tmp_path / "uploads.sqlite3"
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{database_path.as_posix()}",
        poolclass=NullPool,
    )
    asyncio.run(_create_schema(engine))
    harness = UploadHarness(
        engine=engine,
        sessions=async_sessionmaker(engine, expire_on_commit=False),
        storage=LocalProjectStorage(tmp_path / "storage"),
    )
    yield harness
    asyncio.run(engine.dispose())


@pytest.fixture
def upload_client(upload_harness: UploadHarness) -> Iterator[TestClient]:
    settings = Settings(
        _env_file=None,
        app_env="test",
        log_level="CRITICAL",
        jwt_secret_key="integration-test-secret-at-least-32-characters",
        upload_root=upload_harness.storage.root,
        max_single_file_mb=1,
        max_project_size_mb=2,
        max_file_count=10,
        max_total_lines=10,
    )
    runtime = RuntimeContext(
        dependencies=(
            FakeHealthDependency(name="database"),
            FakeHealthDependency(name="redis"),
        ),
        session_factory=upload_harness.sessions,
        project_storage=upload_harness.storage,
    )
    with TestClient(create_app(settings, runtime)) as client:
        yield client


def _register_and_login(client: TestClient, username: str) -> str:
    credentials = {
        "username": username,
        "password": "correct-horse-battery-staple",
    }
    registered = client.post("/api/v1/auth/register", json=credentials)
    assert registered.status_code == 201
    logged_in = client.post("/api/v1/auth/login", json=credentials)
    assert logged_in.status_code == 200
    return str(logged_in.json()["access_token"])


def _authorization(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _initialize(
    client: TestClient,
    token: str,
    files: list[dict[str, Any]],
) -> dict[str, Any]:
    response = client.post(
        "/api/v1/uploads/init",
        headers=_authorization(token),
        json={"project_name": "secure-demo", "files": files},
    )
    assert response.status_code == 201
    return cast(dict[str, Any], response.json())


async def _stored_project(
    sessions: async_sessionmaker[AsyncSession],
    project_id: int,
) -> Project:
    async with sessions() as session:
        project = await session.scalar(select(Project).where(Project.id == project_id))
        assert project is not None
        return project


def test_manifest_batches_completion_ownership_and_safe_project_deletion(
    upload_client: TestClient,
    upload_harness: UploadHarness,
) -> None:
    alice_token = _register_and_login(upload_client, "alice")
    bob_token = _register_and_login(upload_client, "bob")
    python_source = b"\xef\xbb\xbfdef review():\n    return True\n"
    java_source = b"class Review {}\n"
    initialized = _initialize(
        upload_client,
        alice_token,
        [
            {"relative_path": "src/review.py", "size": len(python_source)},
            {"relative_path": "src/Review.java", "size": len(java_source)},
            {"relative_path": "README.md", "size": 12},
            {"relative_path": "node_modules/generated.py", "size": 8},
            {"relative_path": "src/huge.py", "size": 1024 * 1024 + 1},
        ],
    )
    upload_id = initialized["upload_id"]

    assert initialized["total_files"] == 5
    assert initialized["uploaded_files"] == 0
    assert initialized["skipped_files"] == 3
    assert {item["reason"] for item in initialized["manifest"] if item["reason"]} == {
        "EXCLUDED_PATH",
        "SINGLE_FILE_SIZE_EXCEEDED",
        "UNSUPPORTED_FILE_TYPE",
    }

    visible = upload_client.get(
        f"/api/v1/uploads/{upload_id}",
        headers=_authorization(alice_token),
    )
    assert visible.status_code == 200
    assert visible.json()["upload_id"] == upload_id

    hidden = upload_client.get(
        f"/api/v1/uploads/{upload_id}",
        headers=_authorization(bob_token),
    )
    assert hidden.status_code == 404
    assert hidden.json()["code"] == "UPLOAD_NOT_FOUND"

    uploaded = upload_client.post(
        f"/api/v1/uploads/{upload_id}/files",
        headers=_authorization(alice_token),
        files=[
            ("files", ("src/review.py", python_source, "text/x-python")),
            ("files", ("src/Review.java", java_source, "text/x-java-source")),
        ],
    )
    assert uploaded.status_code == 200
    assert uploaded.json()["uploaded_files"] == 2
    assert uploaded.json()["uploaded_size"] == len(python_source) + len(java_source)

    retried = upload_client.post(
        f"/api/v1/uploads/{upload_id}/files",
        headers=_authorization(alice_token),
        files=[("files", ("src/review.py", python_source, "text/x-python"))],
    )
    assert retried.status_code == 200
    assert retried.json()["uploaded_files"] == 2
    assert retried.json()["uploaded_size"] == len(python_source) + len(java_source)

    completed = upload_client.post(
        f"/api/v1/uploads/{upload_id}/complete",
        headers=_authorization(alice_token),
    )
    assert completed.status_code == 200
    body = completed.json()
    project_id = int(body["project"]["id"])
    assert body["upload"]["status"] == "completed"
    assert body["project"]["total_files"] == 2
    assert body["project"]["total_lines"] == 3
    assert body["project"]["language_stats"] == {"java": 1, "python": 1}

    repeated = upload_client.post(
        f"/api/v1/uploads/{upload_id}/complete",
        headers=_authorization(alice_token),
    )
    assert repeated.status_code == 200
    assert repeated.json()["project"]["id"] == project_id

    detail = upload_client.get(
        f"/api/v1/projects/{project_id}",
        headers=_authorization(alice_token),
    )
    assert detail.status_code == 200
    assert [item["relative_path"] for item in detail.json()["files"]] == [
        "src/Review.java",
        "src/review.py",
    ]
    stored = asyncio.run(_stored_project(upload_harness.sessions, project_id))
    project_root = upload_harness.storage.root / stored.storage_key
    assert (project_root / "src" / "review.py").read_bytes() == python_source
    assert (project_root / "src" / "Review.java").read_bytes() == java_source

    deleted = upload_client.delete(
        f"/api/v1/projects/{project_id}",
        headers=_authorization(alice_token),
    )
    assert deleted.status_code == 204
    assert not project_root.exists()


@pytest.mark.parametrize(
    "relative_path",
    ["../escape.py", "/absolute.py", "src\\windows.py", "src/con.py"],
)
def test_manifest_rejects_unsafe_paths(
    upload_client: TestClient,
    relative_path: str,
) -> None:
    token = _register_and_login(upload_client, "owner")
    response = upload_client.post(
        "/api/v1/uploads/init",
        headers=_authorization(token),
        json={
            "project_name": "unsafe",
            "files": [{"relative_path": relative_path, "size": 1}],
        },
    )

    assert response.status_code == 422
    assert response.json()["code"] == "UNSAFE_UPLOAD_PATH"


def test_content_rejections_are_recorded_without_hiding_valid_coverage(
    upload_client: TestClient,
) -> None:
    token = _register_and_login(upload_client, "reviewer")
    valid_source = b"print('ok')\n"
    gb18030_source = "# 中文注释\n".encode("gb18030")
    binary_source = b"print\x00('bad')"
    mismatch_source = b"print('different size')\n"
    initialized = _initialize(
        upload_client,
        token,
        [
            {"relative_path": "valid.py", "size": len(valid_source)},
            {"relative_path": "gb18030.py", "size": len(gb18030_source)},
            {"relative_path": "binary.py", "size": len(binary_source)},
            {"relative_path": "mismatch.py", "size": 1},
        ],
    )
    upload_id = initialized["upload_id"]

    unknown = upload_client.post(
        f"/api/v1/uploads/{upload_id}/files",
        headers=_authorization(token),
        files=[("files", ("undeclared.py", valid_source, "text/plain"))],
    )
    assert unknown.status_code == 422
    assert unknown.json()["code"] == "FILE_NOT_IN_MANIFEST"

    uploaded = upload_client.post(
        f"/api/v1/uploads/{upload_id}/files",
        headers=_authorization(token),
        files=[
            ("files", ("valid.py", valid_source, "text/plain")),
            ("files", ("gb18030.py", gb18030_source, "text/plain")),
            ("files", ("binary.py", binary_source, "application/octet-stream")),
            ("files", ("mismatch.py", mismatch_source, "text/plain")),
        ],
    )
    assert uploaded.status_code == 200
    body = uploaded.json()
    assert body["uploaded_files"] == 2
    assert body["skipped_files"] == 1
    assert body["failed_files"] == 1
    outcomes = {item["relative_path"]: item for item in body["manifest"]}
    assert outcomes["gb18030.py"]["encoding"] == "gb18030"
    assert outcomes["binary.py"]["reason"] == "BINARY_FILE"
    assert outcomes["mismatch.py"]["reason"] == "FILE_SIZE_MISMATCH"

    completed = upload_client.post(
        f"/api/v1/uploads/{upload_id}/complete",
        headers=_authorization(token),
    )
    assert completed.status_code == 200
    assert completed.json()["project"]["total_files"] == 2


def test_upload_state_conflicts_and_content_limits_have_stable_errors(
    upload_client: TestClient,
) -> None:
    token = _register_and_login(upload_client, "state-owner")
    source = b"print('ready')\n"
    initialized = _initialize(
        upload_client,
        token,
        [{"relative_path": "ready.py", "size": len(source)}],
    )
    upload_id = initialized["upload_id"]

    incomplete = upload_client.post(
        f"/api/v1/uploads/{upload_id}/complete",
        headers=_authorization(token),
    )
    assert incomplete.status_code == 409
    assert incomplete.json()["code"] == "UPLOAD_INCOMPLETE"
    assert incomplete.json()["details"]["pending_count"] == 1

    uploaded = upload_client.post(
        f"/api/v1/uploads/{upload_id}/files",
        headers=_authorization(token),
        files=[("files", ("ready.py", source, "text/plain"))],
    )
    assert uploaded.status_code == 200
    completed = upload_client.post(
        f"/api/v1/uploads/{upload_id}/complete",
        headers=_authorization(token),
    )
    assert completed.status_code == 200

    terminal = upload_client.post(
        f"/api/v1/uploads/{upload_id}/files",
        headers=_authorization(token),
        files=[("files", ("ready.py", source, "text/plain"))],
    )
    assert terminal.status_code == 409
    assert terminal.json()["code"] == "UPLOAD_ALREADY_COMPLETED"

    mime_initialized = _initialize(
        upload_client,
        token,
        [{"relative_path": "pretend.py", "size": len(source)}],
    )
    mime_upload = upload_client.post(
        f"/api/v1/uploads/{mime_initialized['upload_id']}/files",
        headers=_authorization(token),
        files=[("files", ("pretend.py", source, "image/png"))],
    )
    assert mime_upload.status_code == 200
    assert mime_upload.json()["manifest"][0]["reason"] == "UNSUPPORTED_MIME_TYPE"
    empty_completion = upload_client.post(
        f"/api/v1/uploads/{mime_initialized['upload_id']}/complete",
        headers=_authorization(token),
    )
    assert empty_completion.status_code == 409
    assert empty_completion.json()["code"] == "UPLOAD_HAS_NO_ACCEPTED_FILES"


def test_manifest_enforces_duplicate_count_and_project_size_limits(
    upload_client: TestClient,
) -> None:
    token = _register_and_login(upload_client, "limit-owner")

    duplicate = upload_client.post(
        "/api/v1/uploads/init",
        headers=_authorization(token),
        json={
            "project_name": "duplicates",
            "files": [
                {"relative_path": "src/Review.py", "size": 1},
                {"relative_path": "src/review.py", "size": 1},
            ],
        },
    )
    assert duplicate.status_code == 422
    assert duplicate.json()["code"] == "DUPLICATE_UPLOAD_PATH"

    too_many = upload_client.post(
        "/api/v1/uploads/init",
        headers=_authorization(token),
        json={
            "project_name": "too-many",
            "files": [{"relative_path": f"src/file_{index}.py", "size": 1} for index in range(11)],
        },
    )
    assert too_many.status_code == 422
    assert too_many.json()["code"] == "UPLOAD_FILE_COUNT_EXCEEDED"

    too_large = upload_client.post(
        "/api/v1/uploads/init",
        headers=_authorization(token),
        json={
            "project_name": "too-large",
            "files": [
                {"relative_path": f"src/file_{index}.py", "size": 1024 * 1024} for index in range(3)
            ],
        },
    )
    assert too_large.status_code == 422
    assert too_large.json()["code"] == "UPLOAD_PROJECT_SIZE_EXCEEDED"
