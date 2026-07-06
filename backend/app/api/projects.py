"""Owner-scoped project resource endpoints."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import CurrentUser
from app.core.dependencies import ProjectStorageDependency, get_session
from app.models.project import Project
from app.schemas.common import ErrorResponse
from app.schemas.project import ProjectDetailResponse, ProjectResponse
from app.services.project_service import ProjectService

router = APIRouter(prefix="/projects", tags=["projects"])
SessionDependency = Annotated[AsyncSession, Depends(get_session)]
PROJECT_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "Authentication required"},
    404: {"model": ErrorResponse, "description": "Project not found for this user"},
    422: {"model": ErrorResponse, "description": "Request validation failed"},
}


@router.get(
    "",
    response_model=list[ProjectResponse],
    responses={401: PROJECT_ERROR_RESPONSES[401]},
)
async def list_projects(
    current_user: CurrentUser,
    session: SessionDependency,
) -> list[Project]:
    """List only projects owned by the authenticated user."""
    return await ProjectService(session).list_for_user(current_user.id)


@router.get(
    "/{project_id}",
    response_model=ProjectDetailResponse,
    responses=PROJECT_ERROR_RESPONSES,
)
async def get_project(
    project_id: int,
    current_user: CurrentUser,
    session: SessionDependency,
) -> Project:
    """Return project and file metadata only when the caller owns it."""
    return await ProjectService(session).get_for_user(project_id, current_user.id)


@router.delete(
    "/{project_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    responses=PROJECT_ERROR_RESPONSES,
)
async def delete_project(
    project_id: int,
    current_user: CurrentUser,
    session: SessionDependency,
    storage: ProjectStorageDependency,
) -> Response:
    """Delete an owned project and its database-registered file metadata."""
    await ProjectService(session, storage).delete_for_user(project_id, current_user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
