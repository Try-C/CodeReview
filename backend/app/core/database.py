"""SQLAlchemy engine, sessions, and declarative model base."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class shared by every persisted domain model."""


SessionFactory = async_sessionmaker[AsyncSession]


class DatabaseDependency:
    """Own the async SQLAlchemy engine and request-scoped session factory."""

    name = "database"

    def __init__(self, database_url: str) -> None:
        self._engine: AsyncEngine = create_async_engine(
            database_url,
            pool_pre_ping=True,
        )
        self.session_factory: SessionFactory = async_sessionmaker(
            self._engine,
            expire_on_commit=False,
        )

    async def check(self) -> None:
        """Run a minimal round trip without changing database state."""
        async with self._engine.connect() as connection:
            await connection.execute(text("SELECT 1"))

    async def close(self) -> None:
        """Release all pooled database connections."""
        await self._engine.dispose()
