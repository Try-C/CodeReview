"""Application health endpoints."""

from typing import cast

from fastapi import APIRouter, Request, status

from app.core.config import Settings
from app.schemas.health import LiveHealthResponse, ReadyHealthResponse

router = APIRouter(prefix="/health", tags=["health"])


def _settings_from(request: Request) -> Settings:
    """Return the settings instance attached during application creation."""
    return cast(Settings, request.app.state.settings)


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
    """Return readiness checks for dependencies currently wired into the app."""
    settings = _settings_from(request)
    return ReadyHealthResponse(
        service=settings.app_name,
        version=settings.app_version,
        checks={"configuration": "ok"},
    )
