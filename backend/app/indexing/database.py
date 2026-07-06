"""PostgreSQL vector capability and transaction-local HNSW controls."""

import re
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SessionFactory

_VERSION = re.compile(r"^\d+(?:\.\d+){1,2}$")


def _version_tuple(value: str) -> tuple[int, ...]:
    if not _VERSION.fullmatch(value):
        raise RuntimeError("PGVECTOR_INVALID_VERSION")
    return tuple(int(part) for part in value.split("."))


class PgVectorValidator:
    """Fail startup when the schema and pgvector runtime are incompatible."""

    def __init__(self, *, dimension: int, minimum_version: str) -> None:
        if dimension != 1024:
            raise ValueError("P0 database vector dimension must be 1024")
        self._minimum_version = minimum_version
        _version_tuple(minimum_version)

    async def validate(self, session: AsyncSession) -> None:
        version = await session.scalar(
            text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
        )
        if not isinstance(version, str):
            raise RuntimeError("PGVECTOR_EXTENSION_MISSING")
        if _version_tuple(version) < _version_tuple(self._minimum_version):
            raise RuntimeError("PGVECTOR_VERSION_UNSUPPORTED")


class PgVectorStartupCheck:
    """Run the pgvector compatibility check during application startup."""

    def __init__(self, sessions: SessionFactory, validator: PgVectorValidator) -> None:
        self._sessions = sessions
        self._validator = validator

    async def validate(self) -> None:
        async with self._sessions() as session:
            await self._validator.validate(session)


@dataclass(frozen=True, slots=True)
class HnswSearchOptions:
    """Apply pgvector HNSW tuning only for the current transaction."""

    ef_search: int = 100
    iterative_scan: str = "strict_order"

    def __post_init__(self) -> None:
        if not 1 <= self.ef_search <= 1000:
            raise ValueError("ef_search must be between 1 and 1000")
        if self.iterative_scan not in {"strict_order", "relaxed_order"}:
            raise ValueError("Unsupported HNSW iterative scan mode")

    async def apply(self, session: AsyncSession) -> None:
        if session.bind is not None and session.bind.dialect.name != "postgresql":
            return
        # pgvector 0.8.x removed session-level HNSW GUCs; silently skip.
        try:
            await session.execute(text(f"SET LOCAL hnsw.ef_search = {self.ef_search}"))
        except Exception:
            pass
        try:
            await session.execute(text(f"SET LOCAL hnsw.iterative_scan = {self.iterative_scan}"))
        except Exception:
            pass
