"""Celery entry point for the outer asynchronous review pipeline."""

import asyncio
from decimal import Decimal

import httpx

from app.core.config import Settings, get_settings
from app.core.database import DatabaseDependency
from app.core.redis import RedisDependency
from app.indexing import (
    DashScopeEmbeddingProvider,
    EmbeddingProvider,
    IndexingService,
    UnavailableEmbeddingProvider,
)
from app.languages import create_default_registry
from app.llm import LLMClient, UnavailableLLMProvider
from app.retrieval import ContextAssembler, HybridRetriever
from app.scanner import FileFilter, FileScanner, PriorityClassifier
from app.services.progress_service import ProgressService
from app.services.review_workflow_service import ReviewWorkflowService
from app.storage.local import LocalProjectStorage
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
    await run_review_pipeline_for_task(settings, database, redis, task_id)


async def run_review_pipeline_for_task(
    settings: Settings,
    database: DatabaseDependency,
    redis: RedisDependency,
    task_id: int,
) -> None:
    storage = LocalProjectStorage(settings.upload_root)
    scanner = FileScanner(
        storage,
        FileFilter(settings),
        PriorityClassifier(),
    )
    embedding_http: httpx.AsyncClient | None = None
    try:
        embedding_provider: EmbeddingProvider
        if settings.dashscope_api_key is None:
            embedding_provider = UnavailableEmbeddingProvider()
        else:
            embedding_http = httpx.AsyncClient(base_url=settings.dashscope_base_url)
            embedding_provider = DashScopeEmbeddingProvider(
                embedding_http,
                api_key=settings.dashscope_api_key.get_secret_value(),
                model=settings.embedding_model,
                dimension=settings.embedding_dimension,
                max_batch_size=settings.embedding_batch_size,
            )
        llm_provider = (
            UnavailableLLMProvider()
            if settings.deepseek_api_key is None
            else LLMClient(
                model=settings.llm_model,
                base_url=settings.llm_base_url,
                api_key=settings.deepseek_api_key.get_secret_value(),
                temperature=settings.llm_temperature,
                input_price_per_million=Decimal(settings.llm_input_price_per_million),
                output_price_per_million=Decimal(settings.llm_output_price_per_million),
                pricing_currency=settings.llm_pricing_currency,
                pricing_version=settings.llm_pricing_version,
            )
        )
        indexing = IndexingService(
            database.session_factory,
            embedding_provider,
            embedding_version=settings.embedding_version,
            batch_size=settings.embedding_batch_size,
            max_input_tokens=settings.embedding_max_input_tokens,
        )
        retriever = HybridRetriever(
            database.session_factory,
            embedding_provider,
            rrf_k=settings.rrf_k,
            top_k=settings.top_k,
            max_top_k=settings.max_top_k,
        )
        workflow = ReviewWorkflowService(
            settings=settings,
            sessions=database.session_factory,
            storage=storage,
            languages=create_default_registry(settings),
            indexing=indexing,
            retriever=retriever,
            context_assembler=ContextAssembler(
                database.session_factory,
                max_token_budget=settings.max_token_budget,
            ),
            llm_provider=llm_provider,
        )
        await ProgressService(
            database.session_factory,
            redis,
            scanner,
            workflow=workflow.run,
        ).run_task_lifecycle(task_id)
    finally:
        if embedding_http is not None:
            await embedding_http.aclose()
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
