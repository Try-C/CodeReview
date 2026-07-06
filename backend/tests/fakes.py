"""Deterministic external dependency fakes for backend tests."""

from dataclasses import dataclass

from app.core.redis import StreamNotice


@dataclass(slots=True)
class FakeHealthDependency:
    """Record lifecycle calls and optionally fail a health check."""

    name: str
    check_error: Exception | None = None
    check_calls: int = 0
    close_calls: int = 0

    async def check(self) -> None:
        self.check_calls += 1
        if self.check_error is not None:
            raise self.check_error

    async def close(self) -> None:
        self.close_calls += 1


@dataclass(slots=True)
class FakeTaskDispatcher:
    """Record stable task dispatches without running a worker."""

    task_ids: list[int]
    error: Exception | None = None

    async def dispatch_review(self, task_id: int) -> str:
        self.task_ids.append(task_id)
        if self.error is not None:
            raise self.error
        return f"review-{task_id}"


@dataclass(slots=True)
class FakeTaskEventBus:
    """Record publications and provide deterministic non-blocking waits."""

    published: list[tuple[int, int]]
    publish_error: Exception | None = None

    async def publish(self, task_id: int, event_id: int) -> None:
        if self.publish_error is not None:
            raise self.publish_error
        self.published.append((task_id, event_id))

    async def wait(
        self,
        task_id: int,
        *,
        after_stream_id: str,
        block_milliseconds: int,
    ) -> list[StreamNotice]:
        del task_id, after_stream_id, block_milliseconds
        return []
