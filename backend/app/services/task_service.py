"""Transactional review-task lifecycle and durable progress events."""

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.core.redis import TaskEventBus
from app.models.project import Project
from app.models.task import ReviewTask, TaskEvent
from app.schemas.task import TERMINAL_TASK_STATUSES, ReviewCreateRequest
from app.tasks.celery_app import TaskDispatcher

logger = logging.getLogger(__name__)


class TaskService:
    """Create, query and cancel owner-scoped tasks with append-only events."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        event_bus: TaskEventBus | None = None,
        dispatcher: TaskDispatcher | None = None,
    ) -> None:
        self._session = session
        self._event_bus = event_bus
        self._dispatcher = dispatcher

    async def create(
        self,
        project_id: int,
        user_id: int,
        payload: ReviewCreateRequest,
    ) -> tuple[ReviewTask, bool]:
        """Create exactly one task per owner key and enqueue it after commit."""
        await self._require_owned_project(project_id, user_id)
        existing = await self._session.scalar(
            select(ReviewTask).where(
                ReviewTask.user_id == user_id,
                ReviewTask.idempotency_key == payload.idempotency_key,
            )
        )
        if existing is not None:
            return await self._ensure_dispatched(existing), False

        task = ReviewTask(
            user_id=user_id,
            project_id=project_id,
            idempotency_key=payload.idempotency_key,
            review_mode=payload.review_mode,
            status="pending",
            current_stage="queued",
        )
        event = TaskEvent(
            task=task,
            event_type="queued",
            stage="queued",
            progress=0,
            message="Review task queued",
        )
        self._session.add_all((task, event))
        try:
            await self._session.commit()
        except IntegrityError:
            await self._session.rollback()
            conflicting_task = await self._session.scalar(
                select(ReviewTask).where(
                    ReviewTask.user_id == user_id,
                    ReviewTask.idempotency_key == payload.idempotency_key,
                )
            )
            if conflicting_task is None:
                raise
            return await self._ensure_dispatched(conflicting_task), False

        await self._session.refresh(task)
        await self._session.refresh(event)
        await self._publish(event)
        return await self._ensure_dispatched(task), True

    async def get_for_user(self, task_id: int, user_id: int) -> ReviewTask:
        """Return a task only when it belongs to the authenticated user."""
        task = await self._session.scalar(
            select(ReviewTask).where(ReviewTask.id == task_id, ReviewTask.user_id == user_id)
        )
        if task is None:
            raise self._not_found(task_id)
        return task

    async def cancel(self, task_id: int, user_id: int) -> ReviewTask:
        """Request cooperative cancellation once and preserve completed results."""
        task = await self._session.scalar(
            select(ReviewTask)
            .where(ReviewTask.id == task_id, ReviewTask.user_id == user_id)
            .with_for_update()
        )
        if task is None:
            raise self._not_found(task_id)
        if task.status in TERMINAL_TASK_STATUSES or task.cancel_requested:
            return task

        task.cancel_requested = True
        task.status = "cancel_requested"
        event = TaskEvent(
            task_id=task.id,
            event_type="cancel_requested",
            stage=task.current_stage,
            progress=task.progress,
            message="Cancellation requested",
        )
        self._session.add(event)
        await self._session.commit()
        await self._session.refresh(task)
        await self._session.refresh(event)
        await self._publish(event)
        return task

    async def list_events_after(
        self,
        task_id: int,
        *,
        after_event_id: int,
        limit: int,
    ) -> list[TaskEvent]:
        """Read canonical events in strictly increasing database-ID order."""
        events = await self._session.scalars(
            select(TaskEvent)
            .where(TaskEvent.task_id == task_id, TaskEvent.id > after_event_id)
            .order_by(TaskEvent.id)
            .limit(limit)
        )
        return list(events)

    async def _ensure_dispatched(self, task: ReviewTask) -> ReviewTask:
        if task.celery_task_id is not None or task.status in TERMINAL_TASK_STATUSES:
            return task
        if self._dispatcher is None:
            raise RuntimeError("Task dispatcher is not configured")
        try:
            task.celery_task_id = await self._dispatcher.dispatch_review(task.id)
            await self._session.commit()
            await self._session.refresh(task)
            return task
        except Exception as exc:
            task_id = task.id
            await self._session.rollback()
            failed_task = await self._session.get(ReviewTask, task_id)
            if failed_task is not None:
                failed_task.status = "failed"
                failed_task.current_stage = "queued"
                failed_task.error_code = "TASK_DISPATCH_FAILED"
                failed_task.error_message = "Review task could not be queued"
                failed_task.finished_at = datetime.now(UTC)
                event = TaskEvent(
                    task_id=failed_task.id,
                    event_type="final",
                    stage="queued",
                    progress=failed_task.progress,
                    message="Review task dispatch failed",
                    metadata_={"status": "failed", "error_code": "TASK_DISPATCH_FAILED"},
                )
                self._session.add(event)
                await self._session.commit()
                await self._session.refresh(event)
                await self._publish(event)
            raise AppError(
                code="TASK_DISPATCH_FAILED",
                message="Review task could not be queued",
                status_code=503,
                details={"task_id": failed_task.id if failed_task is not None else None},
            ) from exc

    async def _require_owned_project(self, project_id: int, user_id: int) -> None:
        project_id_result = await self._session.scalar(
            select(Project.id).where(Project.id == project_id, Project.user_id == user_id)
        )
        if project_id_result is None:
            raise AppError(
                code="PROJECT_NOT_FOUND",
                message="Project does not exist",
                status_code=404,
                details={"project_id": project_id},
            )

    async def _publish(self, event: TaskEvent) -> None:
        if self._event_bus is None:
            return
        try:
            await self._event_bus.publish(event.task_id, event.id)
        except Exception:
            logger.warning(
                "task_event_publish_failed",
                extra={"task_id": event.task_id, "event_id": event.id},
            )

    @staticmethod
    def _not_found(task_id: int) -> AppError:
        return AppError(
            code="REVIEW_TASK_NOT_FOUND",
            message="Review task does not exist",
            status_code=404,
            details={"task_id": task_id},
        )
