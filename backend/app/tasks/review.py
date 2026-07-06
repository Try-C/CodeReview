"""Celery entry point for the outer asynchronous review pipeline."""

import asyncio

from app.core.config import get_settings
from app.core.database import DatabaseDependency
from app.core.redis import RedisDependency
from app.services.progress_service import ProgressService
from app.tasks.celery_app import celery_app


@celery_app.task(name="app.tasks.review.run_review_pipeline")  # type: ignore[untyped-decorator]
def run_review_pipeline(task_id: int) -> None:
    """Run the review lifecycle outside the HTTP process."""
    asyncio.run(_run_review_pipeline(task_id))


@celery_app.task(name="app.tasks.review.cleanup_task_events")  # type: ignore[untyped-decorator]
def cleanup_task_events() -> None:
    """Remove expired event history according to the shared retention setting."""
    asyncio.run(_cleanup_task_events())


async def _run_review_pipeline(task_id: int) -> None:
    settings = get_settings()
    database = DatabaseDependency(settings.database_url.get_secret_value())
    redis = RedisDependency(
        settings.redis_url.get_secret_value(),
        stream_max_length=settings.task_event_stream_max_length,
    )
    try:
        await ProgressService(database.session_factory, redis).run_task_lifecycle(task_id)
    finally:
        await redis.close()
        await database.close()


async def _cleanup_task_events() -> None:
    settings = get_settings()
    database = DatabaseDependency(settings.database_url.get_secret_value())
    try:
        await ProgressService(database.session_factory).delete_expired_events(
            settings.task_event_retention_days
        )
    finally:
        await database.close()
