"""Worker-side atomic state transitions and best-effort stream publication."""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.redis import TaskEventBus
from app.models.task import ReviewTask, TaskEvent
from app.schemas.task import TERMINAL_TASK_STATUSES

logger = logging.getLogger(__name__)


class ProgressService:
    """Apply retry-safe worker lifecycle transitions at transaction boundaries."""

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        event_bus: TaskEventBus | None = None,
    ) -> None:
        self._sessions = sessions
        self._event_bus = event_bus

    async def run_task_lifecycle(self, task_id: int) -> None:
        """Exercise the outer task boundary; later modules insert stages here."""
        try:
            started = await self._start_or_cancel(task_id)
            if not started:
                return
            await self._finish(task_id)
        except Exception:
            logger.exception("review_task_failed", extra={"task_id": task_id})
            await self._fail(task_id)
            raise

    async def delete_expired_events(self, retention_days: int) -> None:
        """Delete event history older than the configured retention window."""
        cutoff = datetime.now(UTC) - timedelta(days=retention_days)
        async with self._sessions() as session:
            await session.execute(delete(TaskEvent).where(TaskEvent.created_at < cutoff))
            await session.commit()

    async def _start_or_cancel(self, task_id: int) -> bool:
        async with self._sessions() as session:
            task = await session.scalar(
                select(ReviewTask).where(ReviewTask.id == task_id).with_for_update()
            )
            if task is None or task.status in TERMINAL_TASK_STATUSES:
                return False
            if task.cancel_requested or task.status == "cancel_requested":
                task.status = "cancelled"
                task.current_stage = "cancelled"
                task.finished_at = datetime.now(UTC)
                event = TaskEvent(
                    task_id=task.id,
                    event_type="final",
                    stage="cancelled",
                    progress=task.progress,
                    message="Review task cancelled",
                    metadata_={"status": "cancelled"},
                )
                session.add(event)
                await session.commit()
                await session.refresh(event)
                await self._publish(event)
                return False

            task.status = "scanning"
            task.current_stage = "task_setup"
            task.progress = 1
            task.started_at = task.started_at or datetime.now(UTC)
            event = TaskEvent(
                task_id=task.id,
                event_type="progress",
                stage="task_setup",
                progress=1,
                message="Review worker started",
            )
            session.add(event)
            await session.commit()
            await session.refresh(event)
            await self._publish(event)
            return True

    async def _finish(self, task_id: int) -> None:
        async with self._sessions() as session:
            task = await session.scalar(
                select(ReviewTask).where(ReviewTask.id == task_id).with_for_update()
            )
            if task is None or task.status in TERMINAL_TASK_STATUSES:
                return
            if task.cancel_requested or task.status == "cancel_requested":
                status = "cancelled"
                message = "Review task cancelled"
            else:
                status = "success"
                message = "Review task infrastructure pipeline completed"
                task.progress = 100
            task.status = status
            task.current_stage = status
            task.finished_at = datetime.now(UTC)
            event = TaskEvent(
                task_id=task.id,
                event_type="final",
                stage=status,
                progress=task.progress,
                message=message,
                metadata_={"status": status},
            )
            session.add(event)
            await session.commit()
            await session.refresh(event)
            await self._publish(event)

    async def _fail(self, task_id: int) -> None:
        async with self._sessions() as session:
            task = await session.scalar(
                select(ReviewTask).where(ReviewTask.id == task_id).with_for_update()
            )
            if task is None or task.status in TERMINAL_TASK_STATUSES:
                return
            task.status = "failed"
            task.current_stage = task.current_stage or "worker"
            task.error_code = "REVIEW_PIPELINE_FAILED"
            task.error_message = "Review worker failed"
            task.finished_at = datetime.now(UTC)
            event = TaskEvent(
                task_id=task.id,
                event_type="final",
                stage=task.current_stage,
                progress=task.progress,
                message="Review worker failed",
                metadata_={"status": "failed", "error_code": "REVIEW_PIPELINE_FAILED"},
            )
            session.add(event)
            await session.commit()
            await session.refresh(event)
            await self._publish(event)

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
