"""FastAPI dependencies backed by the injected runtime context."""

from collections.abc import AsyncIterator
from typing import cast

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.runtime import RuntimeContext


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Yield one isolated database session for the current request."""
    runtime = cast(RuntimeContext, request.app.state.runtime)
    if runtime.session_factory is None:
        raise RuntimeError("Database sessions are not configured")

    async with runtime.session_factory() as session:
        yield session
