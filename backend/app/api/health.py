"""Application health endpoints."""

from typing import cast

from fastapi import APIRouter, Request, status

from app.core.config import Settings
from app.core.exceptions import AppError
from app.core.runtime import RuntimeContext
from app.schemas.health import LiveHealthResponse, ReadyHealthResponse

router = APIRouter(prefix="/health", tags=["health"])


def _settings_from(request: Request) -> Settings:
    """Return the settings instance attached during application creation."""
    return cast(Settings, request.app.state.settings)


def _runtime_from(request: Request) -> RuntimeContext:
    """Return the runtime dependencies attached during application creation."""
    return cast(RuntimeContext, request.app.state.runtime)


@router.get(
    "/live",
    response_model=LiveHealthResponse,
    status_code=status.HTTP_200_OK,
    summary="Check whether the API process is alive",
)
async def live(request: Request) -> LiveHealthResponse:
    """Return process liveness without calling external dependencies."""
    settings = _settings_from(request)
    return LiveHealthResponse(service=settings.app_name, version=settings.app_version)


@router.get(
    "/ready",
    response_model=ReadyHealthResponse,
    status_code=status.HTTP_200_OK,
    summary="Check whether the API is ready to serve requests",
)
async def ready(request: Request) -> ReadyHealthResponse:
    """Return success only when every external dependency is available."""
    settings = _settings_from(request)
    checks = {
        "configuration": "ok",
        **await _runtime_from(request).health_checks(
            timeout_seconds=settings.health_dependency_timeout_seconds
        ),
    }
    if "error" in checks.values():
        raise AppError(
            code="SERVICE_NOT_READY",
            message="One or more service dependencies are unavailable",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            details={"checks": checks},
        )
    return ReadyHealthResponse(
        service=settings.app_name,
        version=settings.app_version,
        checks=checks,
    )
