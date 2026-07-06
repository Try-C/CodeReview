"""Redis connectivity used by application health checks."""

from redis.asyncio import Redis


class RedisHealthDependency:
    """Own the async Redis client and verify server connectivity."""

    name = "redis"

    def __init__(self, redis_url: str) -> None:
        self._client: Redis = Redis.from_url(redis_url, decode_responses=True)

    async def check(self) -> None:
        """Run a minimal Redis PING command."""
        await self._client.ping()

    async def close(self) -> None:
        """Close the client and its connection pool."""
        await self._client.aclose()
