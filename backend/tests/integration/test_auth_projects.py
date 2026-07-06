"""Integration tests for authentication and owner-scoped project APIs."""

import asyncio
import hashlib
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
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
from app.models import Project, ProjectFile, User
from app.storage.local import LocalProjectStorage
from tests.fakes import FakeHealthDependency


@dataclass(frozen=True, slots=True)
class DatabaseHarness:
    """Own the temporary database resources used by API integration tests."""

    engine: AsyncEngine
    sessions: async_sessionmaker[AsyncSession]


async def _create_schema(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


@pytest.fixture
def database_harness(tmp_path: Path) -> Iterator[DatabaseHarness]:
    database_path = tmp_path / "auth-projects.sqlite3"
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{database_path.as_posix()}",
        poolclass=NullPool,
    )
    asyncio.run(_create_schema(engine))
    harness = DatabaseHarness(
        engine=engine,
        sessions=async_sessionmaker(engine, expire_on_commit=False),
    )
    yield harness
    asyncio.run(engine.dispose())


@pytest.fixture
def module_client(
    database_harness: DatabaseHarness,
    tmp_path: Path,
) -> Iterator[TestClient]:
    settings = Settings(
        _env_file=None,
        app_env="test",
        log_level="CRITICAL",
        jwt_secret_key="integration-test-secret-at-least-32-characters",
    )
    runtime = RuntimeContext(
        dependencies=(
            FakeHealthDependency(name="database"),
            FakeHealthDependency(name="redis"),
        ),
        session_factory=database_harness.sessions,
        project_storage=LocalProjectStorage(tmp_path / "uploads"),
    )
    with TestClient(create_app(settings, runtime)) as client:
        yield client


def _register(
    client: TestClient,
    username: str,
    *,
    password: str = "correct-horse-battery-staple",
) -> dict[str, Any]:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "username": username,
            "password": password,
            "email": f"{username}@example.com",
        },
    )
    assert response.status_code == 201
    return cast(dict[str, Any], response.json())


def _login(
    client: TestClient,
    username: str,
    *,
    password: str = "correct-horse-battery-staple",
) -> str:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 1800
    return str(body["access_token"])


def _authorization(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _stored_user(
    sessions: async_sessionmaker[AsyncSession],
    username: str,
) -> User:
    async with sessions() as session:
        user = await session.scalar(select(User).where(User.username == username))
        assert user is not None
        return user


async def _create_project(
    sessions: async_sessionmaker[AsyncSession],
    user_id: int,
    name: str,
) -> int:
    async with sessions() as session:
        project = Project(
            user_id=user_id,
            project_name=name,
            storage_key=hashlib.sha256(f"{user_id}:{name}".encode()).hexdigest()[:32],
            main_language="python",
            language_stats={"python": 1},
            total_files=1,
            total_lines=3,
            total_size=24,
        )
        project.files.append(
            ProjectFile(
                relative_path="src/main.py",
                content_hash="sha256-example",
                language="python",
                size=24,
                line_count=3,
            )
        )
        session.add(project)
        await session.commit()
        return project.id


async def _project_file_count(
    sessions: async_sessionmaker[AsyncSession],
    project_id: int,
) -> int:
    async with sessions() as session:
        count = await session.scalar(
            select(func.count())
            .select_from(ProjectFile)
            .where(ProjectFile.project_id == project_id)
        )
        return int(count or 0)


def test_registration_login_and_current_user_contract(
    module_client: TestClient,
    database_harness: DatabaseHarness,
) -> None:
    registered = _register(module_client, "alice")

    assert registered["username"] == "alice"
    assert registered["email"] == "alice@example.com"
    assert "password" not in registered
    stored = asyncio.run(_stored_user(database_harness.sessions, "alice"))
    assert stored.password_hash.startswith("$argon2")
    assert "correct-horse-battery-staple" not in stored.password_hash

    duplicate = module_client.post(
        "/api/v1/auth/register",
        json={"username": "alice", "password": "another-valid-password"},
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "USERNAME_ALREADY_EXISTS"

    invalid_login = module_client.post(
        "/api/v1/auth/login",
        json={"username": "alice", "password": "wrong-valid-password"},
    )
    assert invalid_login.status_code == 401
    assert invalid_login.json()["code"] == "INVALID_CREDENTIALS"
    assert invalid_login.headers["WWW-Authenticate"] == "Bearer"

    token = _login(module_client, "alice")
    current = module_client.get("/api/v1/auth/me", headers=_authorization(token))

    assert current.status_code == 200
    assert current.json()["id"] == registered["id"]
    assert current.json()["username"] == "alice"


def test_missing_and_tampered_bearer_tokens_are_rejected(
    module_client: TestClient,
) -> None:
    _register(module_client, "alice")
    token = _login(module_client, "alice")

    missing = module_client.get("/api/v1/auth/me")
    header, payload, signature = token.split(".")
    tampered_signature = f"{'a' if signature[0] != 'a' else 'b'}{signature[1:]}"
    tampered_token = ".".join((header, payload, tampered_signature))
    tampered = module_client.get(
        "/api/v1/auth/me",
        headers=_authorization(tampered_token),
    )

    for response in (missing, tampered):
        assert response.status_code == 401
        assert response.json()["code"] == "AUTHENTICATION_REQUIRED"
        assert response.headers["WWW-Authenticate"] == "Bearer"


def test_project_endpoints_enforce_ownership_and_cascade_metadata(
    module_client: TestClient,
    database_harness: DatabaseHarness,
) -> None:
    alice = _register(module_client, "alice")
    bob = _register(module_client, "bob")
    alice_token = _login(module_client, "alice")
    bob_token = _login(module_client, "bob")
    alice_project_id = asyncio.run(
        _create_project(database_harness.sessions, int(alice["id"]), "alice-project")
    )
    asyncio.run(_create_project(database_harness.sessions, int(bob["id"]), "bob-project"))

    alice_projects = module_client.get(
        "/api/v1/projects",
        headers=_authorization(alice_token),
    )
    assert alice_projects.status_code == 200
    assert [project["project_name"] for project in alice_projects.json()] == ["alice-project"]

    hidden = module_client.get(
        f"/api/v1/projects/{alice_project_id}",
        headers=_authorization(bob_token),
    )
    forbidden_delete = module_client.delete(
        f"/api/v1/projects/{alice_project_id}",
        headers=_authorization(bob_token),
    )
    assert hidden.status_code == 404
    assert hidden.json()["code"] == "PROJECT_NOT_FOUND"
    assert forbidden_delete.status_code == 404
    assert asyncio.run(_project_file_count(database_harness.sessions, alice_project_id)) == 1

    detail = module_client.get(
        f"/api/v1/projects/{alice_project_id}",
        headers=_authorization(alice_token),
    )
    assert detail.status_code == 200
    assert detail.json()["files"][0]["relative_path"] == "src/main.py"

    deleted = module_client.delete(
        f"/api/v1/projects/{alice_project_id}",
        headers=_authorization(alice_token),
    )
    assert deleted.status_code == 204
    assert deleted.content == b""
    assert asyncio.run(_project_file_count(database_harness.sessions, alice_project_id)) == 0

    missing = module_client.get(
        f"/api/v1/projects/{alice_project_id}",
        headers=_authorization(alice_token),
    )
    assert missing.status_code == 404
