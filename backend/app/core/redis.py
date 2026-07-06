"""Redis connectivity and best-effort task-event stream notifications."""

from dataclasses import dataclass
from typing import Protocol, cast

from redis.asyncio import Redis


@dataclass(frozen=True, slots=True)
class StreamNotice:
    """A Redis stream cursor paired with the canonical database event ID."""

    stream_id: str
    event_id: int


class TaskEventBus(Protocol):
    """Best-effort real-time transport; PostgreSQL remains the event source of truth."""

    async def publish(self, task_id: int, event_id: int) -> None:
        """Notify listeners that a committed database event is available."""

    async def wait(
        self,
        task_id: int,
        *,
        after_stream_id: str,
        block_milliseconds: int,
    ) -> list[StreamNotice]:
        """Wait for stream notifications after the supplied Redis cursor."""


class RedisDependency:
    """Own one async Redis client for health checks and event notifications."""

    name = "redis"

    def __init__(self, redis_url: str, *, stream_max_length: int = 10_000) -> None:
        self._client: Redis = Redis.from_url(redis_url, decode_responses=True)
        self._stream_max_length = stream_max_length

    async def check(self) -> None:
        """Run a minimal Redis PING command."""
        await self._client.ping()

    async def publish(self, task_id: int, event_id: int) -> None:
        """Append the committed database ID as the stream notification payload."""
        await self._client.xadd(
            self._stream_key(task_id),
            {"event_id": str(event_id)},
            maxlen=self._stream_max_length,
            approximate=True,
        )

    async def wait(
        self,
        task_id: int,
        *,
        after_stream_id: str,
        block_milliseconds: int,
    ) -> list[StreamNotice]:
        """Read notifications while retaining Redis IDs only as transport cursors."""
        response = await self._client.xread(
            {self._stream_key(task_id): after_stream_id},
            count=100,
            block=block_milliseconds,
        )
        notices: list[StreamNotice] = []
        for _, entries in cast(list[tuple[str, list[tuple[str, dict[str, str]]]]], response):
            notices.extend(
                StreamNotice(stream_id=stream_id, event_id=int(fields["event_id"]))
                for stream_id, fields in entries
            )
        return notices

    async def close(self) -> None:
        """Close the Redis connection pool."""
        await self._client.aclose()

    @staticmethod
    def _stream_key(task_id: int) -> str:
        return f"task-events:{task_id}"


# Kept as a compatibility alias for the health-check-only name used in earlier modules.
RedisHealthDependency = RedisDependency
