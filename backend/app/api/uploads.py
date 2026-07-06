"""Owner-scoped secure folder upload endpoints."""

from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, File, Request, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import CurrentUser
from app.core.config import Settings
from app.core.dependencies import ProjectStorageDependency, get_session
from app.models.upload import UploadSession
from app.schemas.common import ErrorResponse
from app.schemas.upload import (
    UploadCompleteResponse,
    UploadInitRequest,
    UploadSessionResponse,
)
from app.services.upload_service import UploadService

router = APIRouter(prefix="/uploads", tags=["uploads"])
SessionDependency = Annotated[AsyncSession, Depends(get_session)]
UploadedFiles = Annotated[
    list[UploadFile],
    File(description="One or more files whose filenames are manifest-relative paths"),
]
UPLOAD_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "Authentication required"},
    404: {"model": ErrorResponse, "description": "Upload not found for this user"},
    409: {"model": ErrorResponse, "description": "Upload state conflict"},
    422: {"model": ErrorResponse, "description": "Manifest or file validation failed"},
}


def _settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


@router.post(
    "/init",
    response_model=UploadSessionResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        401: UPLOAD_ERROR_RESPONSES[401],
        422: UPLOAD_ERROR_RESPONSES[422],
    },
)
async def initialize_upload(
    payload: UploadInitRequest,
    request: Request,
    current_user: CurrentUser,
    session: SessionDependency,
    storage: ProjectStorageDependency,
) -> UploadSession:
    """Create a validated manifest and isolated server-owned staging directory."""
    return await UploadService(session, storage, _settings(request)).initialize(
        current_user.id,
        payload,
    )


@router.post(
    "/{upload_id}/files",
    response_model=UploadSessionResponse,
    responses=UPLOAD_ERROR_RESPONSES,
)
async def upload_files(
    upload_id: str,
    files: UploadedFiles,
    request: Request,
    current_user: CurrentUser,
    session: SessionDependency,
    storage: ProjectStorageDependency,
) -> UploadSession:
    """Stream a multipart batch while validating actual content and limits."""
    return await UploadService(session, storage, _settings(request)).upload_files(
        upload_id,
        current_user.id,
        files,
    )


@router.post(
    "/{upload_id}/complete",
    response_model=UploadCompleteResponse,
    responses=UPLOAD_ERROR_RESPONSES,
)
async def complete_upload(
    upload_id: str,
    request: Request,
    current_user: CurrentUser,
    session: SessionDependency,
    storage: ProjectStorageDependency,
) -> UploadCompleteResponse:
    """Finalize manifest coverage and create the owned project."""
    return await UploadService(session, storage, _settings(request)).complete(
        upload_id,
        current_user.id,
    )


@router.get(
    "/{upload_id}",
    response_model=UploadSessionResponse,
    responses={
        401: UPLOAD_ERROR_RESPONSES[401],
        404: UPLOAD_ERROR_RESPONSES[404],
    },
)
async def get_upload(
    upload_id: str,
    request: Request,
    current_user: CurrentUser,
    session: SessionDependency,
    storage: ProjectStorageDependency,
) -> UploadSession:
    """Return upload coverage only to its owner."""
    return await UploadService(session, storage, _settings(request)).get(
        upload_id,
        current_user.id,
    )
