"""Project API response contracts."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ProjectFileResponse(BaseModel):
    """Safe project-file metadata exposed to the owning user."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    relative_path: str
    content_hash: str | None
    language: str | None
    size: int = Field(ge=0)
    line_count: int = Field(ge=0)
    parse_status: str
    parse_strategy: str | None
    parse_error: str | None
    created_at: datetime
    updated_at: datetime


class ProjectResponse(BaseModel):
    """Project summary used in lists."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    project_name: str
    main_language: str | None
    language_stats: dict[str, int]
    total_files: int = Field(ge=0)
    total_lines: int = Field(ge=0)
    total_size: int = Field(ge=0)
    status: str
    created_at: datetime
    updated_at: datetime


class ProjectDetailResponse(ProjectResponse):
    """Project summary plus its registered file metadata."""

    files: list[ProjectFileResponse]
