"""PostgreSQL connectivity used by application health checks."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


class DatabaseHealthDependency:
    """Own the async SQLAlchemy engine and verify PostgreSQL connectivity."""

    name = "database"

    def __init__(self, database_url: str) -> None:
        self._engine: AsyncEngine = create_async_engine(
            database_url,
            pool_pre_ping=True,
        )

    async def check(self) -> None:
        """Run a minimal round trip without changing database state."""
        async with self._engine.connect() as connection:
            await connection.execute(text("SELECT 1"))

    async def close(self) -> None:
        """Release all pooled database connections."""
        await self._engine.dispose()
