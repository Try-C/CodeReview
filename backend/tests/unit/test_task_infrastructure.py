"""Focused unit tests for Redis transport and Celery worker boundaries."""

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from celery import Celery

from app.api.reviews import _event_stream
from app.core.config import Settings
from app.core.redis import RedisDependency, StreamNotice, TaskEventBus
from app.models.task import TaskEvent
from app.services.task_service import TaskService
from app.tasks import review
from app.tasks.celery_app import CeleryTaskDispatcher, create_celery_app


@dataclass(slots=True)
class FakeRedisClient:
    ping_calls: int = 0
    close_calls: int = 0
    xadd_calls: list[tuple[str, dict[str, str], int, bool]] | None = None

    async def ping(self) -> None:
        self.ping_calls += 1

    async def xadd(
        self,
        key: str,
        fields: dict[str, str],
        *,
        maxlen: int,
        approximate: bool,
    ) -> None:
        assert self.xadd_calls is not None
        self.xadd_calls.append((key, fields, maxlen, approximate))

    async def xread(
        self,
        streams: dict[str, str],
        *,
        count: int,
        block: int,
    ) -> list[tuple[str, list[tuple[str, dict[str, str]]]]]:
        assert streams == {"task-events:7": "0-0"}
        assert count == 100
        assert block == 500
        return [
            (
                "task-events:7",
                [
                    ("100-0", {"event_id": "42"}),
                    ("101-0", {"event_id": "43"}),
                ],
            )
        ]

    async def aclose(self) -> None:
        self.close_calls += 1


def test_redis_dependency_uses_database_id_as_notification_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeRedisClient(xadd_calls=[])
    monkeypatch.setattr(
        "app.core.redis.Redis.from_url",
        lambda *_args, **_kwargs: client,
    )
    dependency = RedisDependency("redis://example", stream_max_length=321)

    async def exercise() -> None:
        await dependency.check()
        await dependency.publish(7, 42)
        notices = await dependency.wait(
            7,
            after_stream_id="0-0",
            block_milliseconds=500,
        )
        assert [(notice.stream_id, notice.event_id) for notice in notices] == [
            ("100-0", 42),
            ("101-0", 43),
        ]
        await dependency.close()

    asyncio.run(exercise())
    assert client.ping_calls == 1
    assert client.close_calls == 1
    assert client.xadd_calls == [
        ("task-events:7", {"event_id": "42"}, 321, True),
    ]


class FakeCelery:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[int], str]] = []

    def send_task(
        self,
        name: str,
        *,
        args: tuple[int],
        task_id: str,
    ) -> None:
        self.calls.append((name, args, task_id))


def test_celery_dispatcher_uses_stable_task_id() -> None:
    app = FakeCelery()
    dispatcher = CeleryTaskDispatcher(cast(Celery, app))

    broker_id = asyncio.run(dispatcher.dispatch_review(17))

    assert broker_id == "review-17"
    assert app.calls == [
        ("app.tasks.review.run_review_pipeline", (17,), "review-17"),
    ]


def test_celery_configuration_is_retry_safe() -> None:
    settings = Settings(_env_file=None, redis_url="redis://localhost:6379/9")
    app = create_celery_app(settings)

    assert app.conf.broker_url == "redis://localhost:6379/9"
    assert app.conf.task_acks_late is True
    assert app.conf.task_reject_on_worker_lost is True
    assert app.conf.task_ignore_result is True
    assert app.conf.beat_schedule["cleanup-expired-task-events"]["schedule"] == 86_400.0


def test_worker_builds_and_closes_its_own_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, int | None]] = []

    class FakeDatabase:
        session_factory = cast(Any, object())

        def __init__(self, url: str) -> None:
            assert url.startswith("postgresql+asyncpg://")

        async def close(self) -> None:
            calls.append(("database_close", None))

    class FakeRedis:
        def __init__(self, url: str, *, stream_max_length: int) -> None:
            assert url.startswith("redis://")
            assert stream_max_length == 10_000

        async def close(self) -> None:
            calls.append(("redis_close", None))

    class FakeProgress:
        def __init__(self, sessions: Any, event_bus: Any) -> None:
            assert sessions is FakeDatabase.session_factory
            assert isinstance(event_bus, FakeRedis)

        async def run_task_lifecycle(self, task_id: int) -> None:
            calls.append(("run", task_id))

    monkeypatch.setattr(review, "DatabaseDependency", FakeDatabase)
    monkeypatch.setattr(review, "RedisDependency", FakeRedis)
    monkeypatch.setattr(review, "ProgressService", FakeProgress)

    asyncio.run(review._run_review_pipeline(23))

    assert calls == [
        ("run", 23),
        ("redis_close", None),
        ("database_close", None),
    ]


class ConnectedRequest:
    async def is_disconnected(self) -> bool:
        return False


class SequencedEvents:
    def __init__(self, batches: list[list[TaskEvent]]) -> None:
        self.batches = batches

    async def list_events_after(
        self,
        task_id: int,
        *,
        after_event_id: int,
        limit: int,
    ) -> list[TaskEvent]:
        del task_id, after_event_id, limit
        return self.batches.pop(0)


class NotifyingBus:
    async def publish(self, task_id: int, event_id: int) -> None:
        del task_id, event_id

    async def wait(
        self,
        task_id: int,
        *,
        after_stream_id: str,
        block_milliseconds: int,
    ) -> list[StreamNotice]:
        assert task_id == 3
        assert after_stream_id == "0-0"
        assert block_milliseconds == 1000
        return [StreamNotice(stream_id="10-0", event_id=2)]


class FailingBus(NotifyingBus):
    async def wait(
        self,
        task_id: int,
        *,
        after_stream_id: str,
        block_milliseconds: int,
    ) -> list[StreamNotice]:
        del task_id, after_stream_id, block_milliseconds
        raise RuntimeError("redis unavailable")


def _event(event_id: int, event_type: str) -> TaskEvent:
    event = TaskEvent(
        task_id=3,
        event_type=event_type,
        stage="test",
        progress=100 if event_type == "final" else 10,
        message=event_type,
        metadata_={"status": "success"} if event_type == "final" else None,
    )
    event.id = event_id
    event.created_at = datetime.now(UTC)
    return event


def test_event_stream_batches_heartbeats_and_stops_on_final() -> None:
    service = SequencedEvents(
        batches=[
            [_event(1, "progress")],
            [],
            [_event(2, "final")],
        ]
    )
    stream = _event_stream(
        request=cast(Any, ConnectedRequest()),
        service=cast(TaskService, service),
        event_bus=cast(TaskEventBus, NotifyingBus()),
        task_id=3,
        after_event_id=0,
        batch_size=1,
        heartbeat_seconds=1,
    )

    async def consume() -> list[str]:
        return [item async for item in stream]

    output = asyncio.run(consume())
    assert output[0].startswith("id: 1\nevent: progress")
    assert output[1] == ": heartbeat\n\n"
    assert output[2].startswith("id: 2\nevent: final")


def test_celery_task_sync_entrypoint_runs_async_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[int] = []

    async def fake_run(task_id: int) -> None:
        calls.append(task_id)

    monkeypatch.setattr(review, "_run_review_pipeline", fake_run)
    cast(Any, review.run_review_pipeline).run(31)

    assert calls == [31]


@pytest.mark.parametrize("event_bus", [None, cast(TaskEventBus, FailingBus())])
def test_event_stream_heartbeats_without_redis(
    event_bus: TaskEventBus | None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = SequencedEvents(batches=[[], [_event(4, "final")]])

    async def no_wait(_seconds: float) -> None:
        return None

    monkeypatch.setattr("app.api.reviews.asyncio.sleep", no_wait)
    stream = _event_stream(
        request=cast(Any, ConnectedRequest()),
        service=cast(TaskService, service),
        event_bus=event_bus,
        task_id=3,
        after_event_id=0,
        batch_size=10,
        heartbeat_seconds=1,
    )

    async def consume() -> list[str]:
        return [item async for item in stream]

    output = asyncio.run(consume())
    assert output[0] == ": heartbeat\n\n"
    assert output[1].startswith("id: 4\nevent: final")


def test_cleanup_worker_uses_configured_retention_and_closes_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, int | None]] = []

    class FakeDatabase:
        session_factory = cast(Any, object())

        def __init__(self, url: str) -> None:
            assert url.startswith("postgresql+asyncpg://")

        async def close(self) -> None:
            calls.append(("database_close", None))

    class FakeProgress:
        def __init__(self, sessions: Any) -> None:
            assert sessions is FakeDatabase.session_factory

        async def delete_expired_events(self, retention_days: int) -> None:
            calls.append(("cleanup", retention_days))

    monkeypatch.setattr(review, "DatabaseDependency", FakeDatabase)
    monkeypatch.setattr(review, "ProgressService", FakeProgress)
    asyncio.run(review._cleanup_task_events())

    assert calls == [("cleanup", 7), ("database_close", None)]

    sync_calls: list[bool] = []

    async def fake_cleanup() -> None:
        sync_calls.append(True)

    monkeypatch.setattr(review, "_cleanup_task_events", fake_cleanup)
    cast(Any, review.cleanup_task_events).run()
    assert sync_calls == [True]
