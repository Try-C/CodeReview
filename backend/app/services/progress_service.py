"""Worker-side atomic state transitions and best-effort stream publication."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.redis import TaskEventBus
from app.models.project import Project, ProjectFile
from app.models.task import ReviewTask, TaskEvent
from app.scanner import FileScanner, ScanReport
from app.schemas.task import TERMINAL_TASK_STATUSES

logger = logging.getLogger(__name__)


class ProgressService:
    """Apply retry-safe worker lifecycle transitions at transaction boundaries."""

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        event_bus: TaskEventBus | None = None,
        scanner: FileScanner | None = None,
        workflow: Callable[[int], Awaitable[None]] | None = None,
    ) -> None:
        self._sessions = sessions
        self._event_bus = event_bus
        self._scanner = scanner
        self._workflow = workflow

    async def run_task_lifecycle(self, task_id: int) -> None:
        """Exercise the outer task boundary; later modules insert stages here."""
        try:
            started = await self._start_or_cancel(task_id)
            if not started:
                return
            if self._scanner is not None:
                await self._scan(task_id)
            if self._workflow is not None:
                await self._workflow(task_id)
            await self._finish(task_id)
        except Exception as exc:
            logger.exception("review_task_failed", extra={"task_id": task_id})
            await self._fail(task_id, exc)
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

    async def _scan(self, task_id: int) -> None:
        if self._scanner is None:
            return
        scan_input = await self._mark_scan_started(task_id)
        if scan_input is None:
            return
        storage_key, registered_paths = scan_input
        report = await asyncio.to_thread(
            self._scanner.scan,
            storage_key,
            registered_paths,
        )
        await self._persist_scan(task_id, report)

    async def _mark_scan_started(
        self,
        task_id: int,
    ) -> tuple[str, tuple[str, ...]] | None:
        async with self._sessions() as session:
            task = await session.scalar(
                select(ReviewTask).where(ReviewTask.id == task_id).with_for_update()
            )
            if task is None or task.status in TERMINAL_TASK_STATUSES:
                return None
            project = await session.get(Project, task.project_id)
            if project is None:
                raise RuntimeError("Review task references a missing project")
            paths = await session.scalars(
                select(ProjectFile.relative_path)
                .where(ProjectFile.project_id == project.id)
                .order_by(ProjectFile.relative_path)
            )
            task.status = "scanning"
            task.current_stage = "file_scan"
            task.progress = max(task.progress, 5)
            project.status = "scanning"
            event = TaskEvent(
                task_id=task.id,
                event_type="progress",
                stage="file_scan",
                progress=task.progress,
                message="Project scan started",
            )
            session.add(event)
            await session.commit()
            await session.refresh(event)
            await self._publish(event)
            return project.storage_key, tuple(paths)

    async def _persist_scan(self, task_id: int, report: ScanReport) -> None:
        async with self._sessions() as session:
            task = await session.scalar(
                select(ReviewTask).where(ReviewTask.id == task_id).with_for_update()
            )
            if task is None or task.status in TERMINAL_TASK_STATUSES:
                return
            project = await session.get(Project, task.project_id)
            if project is None:
                raise RuntimeError("Review task references a missing project")
            project_files = await session.scalars(
                select(ProjectFile).where(ProjectFile.project_id == project.id)
            )
            results = {result.relative_path: result for result in report.files}
            for project_file in project_files:
                result = results.get(project_file.relative_path)
                if result is None:
                    project_file.scan_status = "failed"
                    project_file.scan_reason = "SCANNER_OMITTED"
                    continue
                project_file.scan_status = result.status
                project_file.scan_priority = result.priority
                project_file.scan_reason = result.reason
                if result.status == "included":
                    project_file.language = result.language
                    project_file.size = result.size
                    project_file.line_count = result.line_count

            language_counts: dict[str, int] = {
                str(language): stats.files for language, stats in report.language_stats.items()
            }
            project.main_language = report.main_language
            project.language_stats = language_counts
            project.total_files = report.coverage.included_files
            project.total_lines = report.coverage.included_lines
            project.total_size = report.coverage.included_size
            project.scan_stats = {
                "coverage": report.coverage.model_dump(mode="json"),
                "languages": {
                    language: stats.model_dump(mode="json")
                    for language, stats in report.language_stats.items()
                },
                "priorities": report.priority_stats,
            }
            project.status = "scanned"
            task.current_stage = "file_scan"
            task.progress = max(task.progress, 15)
            event = TaskEvent(
                task_id=task.id,
                event_type="progress",
                stage="file_scan",
                progress=task.progress,
                message="Project scan completed",
                metadata_=project.scan_stats,
            )
            session.add(event)
            await session.commit()
            await session.refresh(event)
            await self._publish(event)

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
            elif task.fallback_reason:
                status = "partial_success"
                message = "Review task completed with partial results"
                task.progress = 100
            else:
                status = "success"
                message = "Review task completed"
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

    async def _fail(self, task_id: int, exc: Exception | None = None) -> None:
        async with self._sessions() as session:
            task = await session.scalar(
                select(ReviewTask).where(ReviewTask.id == task_id).with_for_update()
            )
            if task is None or task.status in TERMINAL_TASK_STATUSES:
                return
            task.status = "failed"
            task.current_stage = task.current_stage or "worker"
            task.error_code = "REVIEW_PIPELINE_FAILED"
            task.error_message = str(exc) if exc else "Review worker failed"
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
