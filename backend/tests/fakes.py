"""Deterministic external dependency fakes for backend tests."""

from dataclasses import dataclass


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
