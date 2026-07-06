"""FastAPI dependencies backed by the injected runtime context."""

from collections.abc import AsyncIterator
from typing import Annotated, cast

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.runtime import RuntimeContext
from app.storage.local import LocalProjectStorage


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Yield one isolated database session for the current request."""
    runtime = cast(RuntimeContext, request.app.state.runtime)
    if runtime.session_factory is None:
        raise RuntimeError("Database sessions are not configured")

    async with runtime.session_factory() as session:
        yield session


def get_project_storage(request: Request) -> LocalProjectStorage:
    """Return the local storage adapter owned by the application runtime."""
    runtime = cast(RuntimeContext, request.app.state.runtime)
    if runtime.project_storage is None:
        raise RuntimeError("Project storage is not configured")
    return runtime.project_storage


ProjectStorageDependency = Annotated[LocalProjectStorage, Depends(get_project_storage)]
