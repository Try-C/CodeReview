"""FastAPI application factory."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import Settings, get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware
from app.core.runtime import RuntimeContext, build_runtime
from app.tasks.runner import TaskRunner

logger = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    runtime: RuntimeContext | None = None,
) -> FastAPI:
    """Build an application with explicit, testable runtime configuration."""
    runtime_settings = settings or get_settings()
    runtime_context = runtime or build_runtime(runtime_settings)
    configure_logging(
        runtime_settings.log_level,
        json_output=runtime_settings.log_json,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        runner = TaskRunner(
                runtime_settings,
                session_factory=runtime_context.session_factory,
                event_bus=runtime_context.event_bus,
            )
        try:
            await runtime_context.validate_startup()
            await runner.start()
            logger.info(
                "application_started",
                extra={
                    "app_env": runtime_settings.app_env,
                    "app_version": runtime_settings.app_version,
                },
            )
            yield
        finally:
            await runner.stop()
            await runtime_context.close()
            logger.info(
                "application_stopped",
                extra={
                    "app_env": runtime_settings.app_env,
                    "app_version": runtime_settings.app_version,
                },
            )

    application = FastAPI(
        title=runtime_settings.app_name,
        version=runtime_settings.app_version,
        debug=runtime_settings.debug,
        openapi_url=f"{runtime_settings.api_v1_prefix}/openapi.json",
        lifespan=lifespan,
    )
    application.state.settings = runtime_settings
    application.state.runtime = runtime_context
    application.add_middleware(
        CORSMiddleware,
        allow_origins=runtime_settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.add_middleware(
        RequestContextMiddleware,
        header_name=runtime_settings.request_id_header,
    )
    register_exception_handlers(application)
    application.include_router(api_router, prefix=runtime_settings.api_v1_prefix)
    return application


app = create_app()
