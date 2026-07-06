"""Owner-scoped asynchronous review task and SSE endpoints."""

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Request, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import CurrentUser
from app.core.dependencies import (
    EventBusDependency,
    TaskDispatcherDependency,
    get_session,
)
from app.core.redis import TaskEventBus
from app.models.task import ReviewTask, TaskEvent
from app.schemas.common import ErrorResponse
from app.schemas.task import ReviewCreateRequest, ReviewTaskResponse, TaskEventResponse
from app.services.task_service import TaskService

logger = logging.getLogger(__name__)
router = APIRouter(tags=["reviews"])
SessionDependency = Annotated[AsyncSession, Depends(get_session)]
LastEventIdHeader = Annotated[int | None, Header(alias="Last-Event-ID", ge=0)]
REVIEW_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "Authentication required"},
    404: {"model": ErrorResponse, "description": "Project or review task not found"},
    422: {"model": ErrorResponse, "description": "Request validation failed"},
    503: {"model": ErrorResponse, "description": "Task queue unavailable"},
}


@router.post(
    "/projects/{project_id}/reviews",
    response_model=ReviewTaskResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses=REVIEW_ERROR_RESPONSES,
)
async def create_review(
    project_id: int,
    payload: ReviewCreateRequest,
    response: Response,
    current_user: CurrentUser,
    session: SessionDependency,
    event_bus: EventBusDependency,
    dispatcher: TaskDispatcherDependency,
) -> ReviewTask:
    """Create and enqueue one task, or return the existing idempotent result."""
    task, created = await TaskService(
        session,
        event_bus=event_bus,
        dispatcher=dispatcher,
    ).create(project_id, current_user.id, payload)
    response.status_code = status.HTTP_202_ACCEPTED if created else status.HTTP_200_OK
    return task


@router.get(
    "/reviews/{task_id}",
    response_model=ReviewTaskResponse,
    responses=REVIEW_ERROR_RESPONSES,
)
async def get_review(
    task_id: int,
    current_user: CurrentUser,
    session: SessionDependency,
) -> ReviewTask:
    """Return current state for an owner-scoped review task."""
    return await TaskService(session).get_for_user(task_id, current_user.id)


@router.post(
    "/reviews/{task_id}/cancel",
    response_model=ReviewTaskResponse,
    responses=REVIEW_ERROR_RESPONSES,
)
async def cancel_review(
    task_id: int,
    current_user: CurrentUser,
    session: SessionDependency,
    event_bus: EventBusDependency,
) -> ReviewTask:
    """Set the cooperative cancellation flag without killing a worker."""
    return await TaskService(session, event_bus=event_bus).cancel(task_id, current_user.id)


@router.get(
    "/reviews/{task_id}/events",
    response_class=StreamingResponse,
    responses=REVIEW_ERROR_RESPONSES,
)
async def stream_review_events(
    task_id: int,
    request: Request,
    current_user: CurrentUser,
    session: SessionDependency,
    event_bus: EventBusDependency,
    last_event_id: LastEventIdHeader = None,
) -> StreamingResponse:
    """Replay missed database events, then use Redis only for live wakeups."""
    service = TaskService(session)
    await service.get_for_user(task_id, current_user.id)
    settings = request.app.state.settings
    stream = _event_stream(
        request=request,
        service=service,
        event_bus=event_bus,
        task_id=task_id,
        after_event_id=last_event_id or 0,
        batch_size=settings.sse_event_batch_size,
        heartbeat_seconds=settings.sse_heartbeat_seconds,
    )
    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


async def _event_stream(
    *,
    request: Request,
    service: TaskService,
    event_bus: TaskEventBus | None,
    task_id: int,
    after_event_id: int,
    batch_size: int,
    heartbeat_seconds: float,
) -> AsyncIterator[str]:
    last_database_id = after_event_id
    redis_cursor = "0-0"
    while not await request.is_disconnected():
        events = await service.list_events_after(
            task_id,
            after_event_id=last_database_id,
            limit=batch_size,
        )
        for event in events:
            last_database_id = event.id
            yield _format_sse(event)
            if event.event_type == "final":
                return
        if len(events) == batch_size:
            continue

        if event_bus is None:
            await asyncio.sleep(heartbeat_seconds)
        else:
            try:
                notices = await event_bus.wait(
                    task_id,
                    after_stream_id=redis_cursor,
                    block_milliseconds=int(heartbeat_seconds * 1000),
                )
                if notices:
                    redis_cursor = notices[-1].stream_id
            except Exception:
                logger.warning("task_event_wait_failed", extra={"task_id": task_id})
                await asyncio.sleep(heartbeat_seconds)
        yield ": heartbeat\n\n"


def _format_sse(event: TaskEvent) -> str:
    payload = TaskEventResponse.model_validate(event).model_dump(mode="json")
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"id: {event.id}\nevent: {event.event_type}\ndata: {data}\n\n"
