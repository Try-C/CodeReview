"""In-process background task runner — replaces Celery on Windows.

Polls the database for pending review tasks and executes them in the
same process so that task dispatch is reliable without a message broker.
"""

from __future__ import annotations

import asyncio
import logging

from app.core.config import Settings
from app.core.database import SessionFactory
from app.core.redis import TaskEventBus

logger = logging.getLogger(__name__)

_POLL_INTERVAL_SECONDS = 3


class TaskRunner:
    """Polls for pending tasks and runs them sequentially in the background.

    The runner is a long-lived coroutine started by the FastAPI lifespan.
    It processes at most one task at a time to avoid resource contention.
    """

    def __init__(
        self,
        settings: Settings,
        session_factory: SessionFactory | None = None,
        event_bus: TaskEventBus | None = None,
    ) -> None:
        self._settings = settings
        self._session_factory = session_factory
        self._event_bus = event_bus
        self._running = False
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """Begin polling in the background."""
        if self._running:
            return
        if self._session_factory is None:
            logger.warning("task_runner_no_session_factory — skipping start")
            return
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        logger.info("task_runner_started")

    async def stop(self) -> None:
        """Cancel the polling loop."""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("task_runner_stopped")

    async def _poll_loop(self) -> None:
        while self._running:
            task_id: int | None = None
            try:
                task_id = await self._claim_pending_task()
                if task_id is not None:
                    logger.info("task_runner_claimed", extra={"task_id": task_id})
                    # Import here to avoid circular dependency
                    from app.tasks.review import run_review_pipeline_for_task
                    from app.core.database import DatabaseDependency
                    from app.core.redis import RedisDependency

                    database = DatabaseDependency(
                        self._settings.database_url.get_secret_value()
                    )
                    redis = RedisDependency(
                        self._settings.redis_url.get_secret_value(),
                        stream_max_length=self._settings.task_event_stream_max_length,
                    )
                    try:
                        await run_review_pipeline_for_task(
                            self._settings, database, redis, task_id,
                        )
                    finally:
                        await redis.close()
                        await database.close()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "task_runner_cycle_failed",
                    extra={"task_id": task_id or "unknown"},
                )
                await asyncio.sleep(_POLL_INTERVAL_SECONDS)

    async def _claim_pending_task(self) -> int | None:
        """Atomically claim one pending task via SELECT ... FOR UPDATE SKIP LOCKED."""
        if self._session_factory is None:
            return None
        from sqlalchemy import select, update

        from app.models.task import ReviewTask

        async with self._session_factory() as session:
            row = await session.scalar(
                select(ReviewTask.id)
                .where(
                    ReviewTask.status == "pending",
                    ReviewTask.celery_task_id.is_(None),
                )
                .order_by(ReviewTask.id)
                .limit(1)
                .with_for_update(skip_locked=True),
            )
            if row is None:
                await asyncio.sleep(_POLL_INTERVAL_SECONDS)
                return None

            task_id: int = int(row)
            await session.execute(
                update(ReviewTask)
                .where(ReviewTask.id == task_id)
                .values(celery_task_id=f"inprocess-{task_id}"),
            )
            await session.commit()
            return task_id
