"""Celery application and non-blocking task dispatcher."""

import asyncio
from typing import Protocol

from celery import Celery

from app.core.config import Settings, get_settings

REVIEW_TASK_NAME = "app.tasks.review.run_review_pipeline"


class TaskDispatcher(Protocol):
    """Queue boundary shared by Celery and deterministic test fakes."""

    async def dispatch_review(self, task_id: int) -> str:
        """Enqueue one stable, idempotent review task and return its broker ID."""


class CeleryTaskDispatcher:
    """Dispatch review tasks without waiting for worker execution."""

    def __init__(self, app: Celery) -> None:
        self._app = app

    async def dispatch_review(self, task_id: int) -> str:
        broker_task_id = f"review-{task_id}"
        await asyncio.to_thread(
            self._app.send_task,
            REVIEW_TASK_NAME,
            args=(task_id,),
            task_id=broker_task_id,
        )
        return broker_task_id


def create_celery_app(settings: Settings) -> Celery:
    """Build Celery with Redis and retry-safe delivery defaults."""
    broker_url = settings.redis_url.get_secret_value()
    app = Celery("codereview-agent", broker=broker_url)
    app.conf.update(
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        task_ignore_result=True,
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        broker_connection_retry_on_startup=True,
        timezone="Asia/Shanghai",
        enable_utc=True,
        imports=("app.tasks.review",),
        beat_schedule={
            "cleanup-expired-task-events": {
                "task": "app.tasks.review.cleanup_task_events",
                "schedule": 86_400.0,
            }
        },
    )
    return app


celery_app = create_celery_app(get_settings())
