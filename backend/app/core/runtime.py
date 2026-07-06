"""Runtime-owned external dependencies and their lifecycle."""

import asyncio
import logging
from dataclasses import dataclass
from typing import Literal, Protocol

from app.core.config import Settings
from app.core.database import DatabaseDependency, SessionFactory
from app.core.redis import RedisHealthDependency
from app.storage.local import LocalProjectStorage

logger = logging.getLogger(__name__)
HealthCheckStatus = Literal["ok", "error"]


class HealthDependency(Protocol):
    """Small boundary shared by real dependencies and deterministic test fakes."""

    name: str

    async def check(self) -> None:
        """Raise when the dependency cannot serve requests."""

    async def close(self) -> None:
        """Release resources owned by the dependency."""


@dataclass(frozen=True, slots=True)
class RuntimeContext:
    """Own process-wide dependencies injected into the FastAPI application."""

    dependencies: tuple[HealthDependency, ...]
    session_factory: SessionFactory | None = None
    project_storage: LocalProjectStorage | None = None

    async def health_checks(
        self,
        *,
        timeout_seconds: float,
    ) -> dict[str, HealthCheckStatus]:
        """Check dependencies concurrently with an independent timeout per check."""
        results = await asyncio.gather(
            *(
                self._check_dependency(
                    dependency,
                    timeout_seconds=timeout_seconds,
                )
                for dependency in self.dependencies
            )
        )
        return dict(results)

    async def close(self) -> None:
        """Close every dependency, even if another close operation fails."""
        results = await asyncio.gather(
            *(dependency.close() for dependency in reversed(self.dependencies)),
            return_exceptions=True,
        )
        for dependency, result in zip(reversed(self.dependencies), results, strict=True):
            if isinstance(result, BaseException):
                logger.error(
                    "dependency_close_failed",
                    extra={"dependency": dependency.name},
                )

    @staticmethod
    async def _check_dependency(
        dependency: HealthDependency,
        *,
        timeout_seconds: float,
    ) -> tuple[str, HealthCheckStatus]:
        try:
            async with asyncio.timeout(timeout_seconds):
                await dependency.check()
        except Exception:
            logger.warning(
                "health_dependency_failed",
                extra={"dependency": dependency.name},
            )
            return dependency.name, "error"
        return dependency.name, "ok"


def build_runtime(settings: Settings) -> RuntimeContext:
    """Build production dependency adapters from validated settings."""
    database = DatabaseDependency(settings.database_url.get_secret_value())
    return RuntimeContext(
        dependencies=(
            database,
            RedisHealthDependency(settings.redis_url.get_secret_value()),
        ),
        session_factory=database.session_factory,
        project_storage=LocalProjectStorage(settings.upload_root),
    )
