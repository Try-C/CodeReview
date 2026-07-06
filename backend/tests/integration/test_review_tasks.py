"""Integration coverage for task idempotency, cancellation and SSE replay."""

import asyncio
import hashlib
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
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
from app.models import Project, ReviewTask, TaskEvent
from app.services.progress_service import ProgressService
from tests.fakes import (
    FakeHealthDependency,
    FakeTaskDispatcher,
    FakeTaskEventBus,
)


@dataclass(frozen=True, slots=True)
class TaskHarness:
    engine: AsyncEngine
    sessions: async_sessionmaker[AsyncSession]
    dispatcher: FakeTaskDispatcher
    event_bus: FakeTaskEventBus


async def _create_schema(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


@pytest.fixture
def task_harness(tmp_path: Path) -> Iterator[TaskHarness]:
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{(tmp_path / 'tasks.sqlite3').as_posix()}",
        poolclass=NullPool,
    )
    asyncio.run(_create_schema(engine))
    harness = TaskHarness(
        engine=engine,
        sessions=async_sessionmaker(engine, expire_on_commit=False),
        dispatcher=FakeTaskDispatcher(task_ids=[]),
        event_bus=FakeTaskEventBus(published=[]),
    )
    yield harness
    asyncio.run(engine.dispose())


@pytest.fixture
def task_client(task_harness: TaskHarness) -> Iterator[TestClient]:
    settings = Settings(
        _env_file=None,
        app_env="test",
        log_level="CRITICAL",
        jwt_secret_key="integration-test-secret-at-least-32-characters",
        sse_heartbeat_seconds=1,
    )
    runtime = RuntimeContext(
        dependencies=(
            FakeHealthDependency(name="database"),
            FakeHealthDependency(name="redis"),
        ),
        session_factory=task_harness.sessions,
        event_bus=task_harness.event_bus,
        task_dispatcher=task_harness.dispatcher,
    )
    with TestClient(create_app(settings, runtime)) as client:
        yield client


def _register_and_login(client: TestClient, username: str) -> tuple[int, str]:
    registered = client.post(
        "/api/v1/auth/register",
        json={"username": username, "password": "correct-horse-battery-staple"},
    )
    assert registered.status_code == 201
    login = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": "correct-horse-battery-staple"},
    )
    assert login.status_code == 200
    return int(registered.json()["id"]), str(login.json()["access_token"])


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


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
        )
        session.add(project)
        await session.commit()
        return project.id


async def _events(
    sessions: async_sessionmaker[AsyncSession],
    task_id: int,
) -> list[TaskEvent]:
    async with sessions() as session:
        result = await session.scalars(
            select(TaskEvent).where(TaskEvent.task_id == task_id).order_by(TaskEvent.id)
        )
        return list(result)


async def _task_count(sessions: async_sessionmaker[AsyncSession]) -> int:
    async with sessions() as session:
        count = await session.scalar(select(func.count()).select_from(ReviewTask))
        return int(count or 0)


async def _age_event(
    sessions: async_sessionmaker[AsyncSession],
    event_id: int,
    *,
    days: int,
) -> None:
    async with sessions() as session:
        await session.execute(
            update(TaskEvent)
            .where(TaskEvent.id == event_id)
            .values(created_at=datetime.now(UTC) - timedelta(days=days))
        )
        await session.commit()


def _create_review(
    client: TestClient,
    project_id: int,
    token: str,
    *,
    key: str = "review-request-1",
) -> Any:
    return client.post(
        f"/api/v1/projects/{project_id}/reviews",
        headers=_auth(token),
        json={"idempotency_key": key, "review_mode": "security"},
    )


def test_creation_is_owner_scoped_and_idempotent(
    task_client: TestClient,
    task_harness: TaskHarness,
) -> None:
    alice_id, alice_token = _register_and_login(task_client, "alice")
    _, bob_token = _register_and_login(task_client, "bob")
    project_id = asyncio.run(_create_project(task_harness.sessions, alice_id, "demo"))

    created = _create_review(task_client, project_id, alice_token)
    repeated = _create_review(task_client, project_id, alice_token)

    assert created.status_code == 202
    assert repeated.status_code == 200
    assert repeated.json()["id"] == created.json()["id"]
    assert asyncio.run(_task_count(task_harness.sessions)) == 1
    assert task_harness.dispatcher.task_ids == [created.json()["id"]]
    events = asyncio.run(_events(task_harness.sessions, created.json()["id"]))
    assert [event.event_type for event in events] == ["queued"]
    assert task_harness.event_bus.published == [(created.json()["id"], events[0].id)]

    hidden = task_client.get(
        f"/api/v1/reviews/{created.json()['id']}",
        headers=_auth(bob_token),
    )
    hidden_cancel = task_client.post(
        f"/api/v1/reviews/{created.json()['id']}/cancel",
        headers=_auth(bob_token),
    )
    assert hidden.status_code == hidden_cancel.status_code == 404
    assert hidden.json()["code"] == "REVIEW_TASK_NOT_FOUND"


def test_cancellation_is_cooperative_and_retry_safe(
    task_client: TestClient,
    task_harness: TaskHarness,
) -> None:
    user_id, token = _register_and_login(task_client, "alice")
    project_id = asyncio.run(_create_project(task_harness.sessions, user_id, "cancel-demo"))
    task_id = int(_create_review(task_client, project_id, token).json()["id"])

    first = task_client.post(f"/api/v1/reviews/{task_id}/cancel", headers=_auth(token))
    repeated = task_client.post(f"/api/v1/reviews/{task_id}/cancel", headers=_auth(token))
    assert first.status_code == repeated.status_code == 200
    assert first.json()["status"] == "cancel_requested"
    assert repeated.json()["cancel_requested"] is True

    asyncio.run(
        ProgressService(task_harness.sessions, task_harness.event_bus).run_task_lifecycle(task_id)
    )
    asyncio.run(
        ProgressService(task_harness.sessions, task_harness.event_bus).run_task_lifecycle(task_id)
    )
    state = task_client.get(f"/api/v1/reviews/{task_id}", headers=_auth(token))
    events = asyncio.run(_events(task_harness.sessions, task_id))
    assert state.json()["status"] == "cancelled"
    assert [event.event_type for event in events] == [
        "queued",
        "cancel_requested",
        "final",
    ]
    assert events[-1].metadata_ == {"status": "cancelled"}


def test_sse_reconnect_replays_database_ids_when_redis_publish_fails(
    task_client: TestClient,
    task_harness: TaskHarness,
) -> None:
    user_id, token = _register_and_login(task_client, "alice")
    project_id = asyncio.run(_create_project(task_harness.sessions, user_id, "sse-demo"))
    task_id = int(_create_review(task_client, project_id, token).json()["id"])
    queued = asyncio.run(_events(task_harness.sessions, task_id))[0]
    task_harness.event_bus.publish_error = RuntimeError("redis unavailable")

    asyncio.run(
        ProgressService(task_harness.sessions, task_harness.event_bus).run_task_lifecycle(task_id)
    )
    stored_events = asyncio.run(_events(task_harness.sessions, task_id))
    response = task_client.get(
        f"/api/v1/reviews/{task_id}/events",
        headers={**_auth(token), "Last-Event-ID": str(queued.id)},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert f"id: {queued.id}\n" not in response.text
    assert [line for line in response.text.splitlines() if line.startswith("id: ")] == [
        f"id: {event.id}" for event in stored_events[1:]
    ]
    assert "event: progress" in response.text
    assert "event: final" in response.text
    assert '"status":"success"' in response.text


def test_missing_project_and_dispatch_failure_use_stable_error_contracts(
    task_client: TestClient,
    task_harness: TaskHarness,
) -> None:
    user_id, token = _register_and_login(task_client, "alice")
    missing = _create_review(task_client, 999_999, token)
    assert missing.status_code == 404
    assert missing.json()["code"] == "PROJECT_NOT_FOUND"

    project_id = asyncio.run(_create_project(task_harness.sessions, user_id, "dispatch-demo"))
    task_harness.dispatcher.error = RuntimeError("broker unavailable")
    failed = _create_review(task_client, project_id, token, key="dispatch-failure")
    assert failed.status_code == 503
    assert failed.json()["code"] == "TASK_DISPATCH_FAILED"
    task_id = int(failed.json()["details"]["task_id"])
    events = asyncio.run(_events(task_harness.sessions, task_id))
    assert [event.event_type for event in events] == ["queued", "final"]
    assert events[-1].metadata_ == {
        "status": "failed",
        "error_code": "TASK_DISPATCH_FAILED",
    }

    state = task_client.get(f"/api/v1/reviews/{task_id}", headers=_auth(token))
    terminal_cancel = task_client.post(
        f"/api/v1/reviews/{task_id}/cancel",
        headers=_auth(token),
    )
    assert state.json()["status"] == terminal_cancel.json()["status"] == "failed"
    assert len(asyncio.run(_events(task_harness.sessions, task_id))) == 2


def test_worker_exception_is_persisted_as_a_final_failure(
    task_client: TestClient,
    task_harness: TaskHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id, token = _register_and_login(task_client, "alice")
    project_id = asyncio.run(_create_project(task_harness.sessions, user_id, "worker-failure"))
    task_id = int(_create_review(task_client, project_id, token, key="worker-failure").json()["id"])

    async def fail_stage(_service: ProgressService, _task_id: int) -> None:
        raise RuntimeError("stage implementation failed")

    monkeypatch.setattr(ProgressService, "_finish", fail_stage)
    with pytest.raises(RuntimeError, match="stage implementation failed"):
        asyncio.run(
            ProgressService(
                task_harness.sessions,
                task_harness.event_bus,
            ).run_task_lifecycle(task_id)
        )

    state = task_client.get(f"/api/v1/reviews/{task_id}", headers=_auth(token))
    events = asyncio.run(_events(task_harness.sessions, task_id))
    assert state.json()["status"] == "failed"
    assert state.json()["error_code"] == "REVIEW_PIPELINE_FAILED"
    assert state.json()["error_message"] == "Review worker failed"
    assert events[-1].event_type == "final"
    assert events[-1].metadata_ == {
        "status": "failed",
        "error_code": "REVIEW_PIPELINE_FAILED",
    }


def test_event_retention_cleanup_deletes_only_expired_history(
    task_client: TestClient,
    task_harness: TaskHarness,
) -> None:
    user_id, token = _register_and_login(task_client, "alice")
    project_id = asyncio.run(_create_project(task_harness.sessions, user_id, "retention"))
    task_id = int(_create_review(task_client, project_id, token, key="retention").json()["id"])
    asyncio.run(ProgressService(task_harness.sessions).run_task_lifecycle(task_id))
    before = asyncio.run(_events(task_harness.sessions, task_id))
    asyncio.run(_age_event(task_harness.sessions, before[0].id, days=8))

    asyncio.run(ProgressService(task_harness.sessions).delete_expired_events(7))

    after = asyncio.run(_events(task_harness.sessions, task_id))
    assert [event.id for event in after] == [event.id for event in before[1:]]
