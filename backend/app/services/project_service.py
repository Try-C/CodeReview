"""Owner-scoped project query and deletion use cases."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import AppError
from app.models.project import Project


class ProjectService:
    """Access projects only through explicit owner-scoped predicates."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_user(self, user_id: int) -> list[Project]:
        projects = await self._session.scalars(
            select(Project)
            .where(Project.user_id == user_id)
            .order_by(Project.created_at.desc(), Project.id.desc())
        )
        return list(projects)

    async def get_for_user(self, project_id: int, user_id: int) -> Project:
        project = await self._session.scalar(
            select(Project)
            .options(selectinload(Project.files))
            .where(Project.id == project_id, Project.user_id == user_id)
        )
        if project is None:
            raise AppError(
                code="PROJECT_NOT_FOUND",
                message="Project does not exist",
                status_code=404,
                details={"project_id": project_id},
            )
        return project

    async def delete_for_user(self, project_id: int, user_id: int) -> None:
        project = await self.get_for_user(project_id, user_id)
        await self._session.delete(project)
        await self._session.commit()
