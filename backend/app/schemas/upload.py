"""Request, response, and persisted manifest contracts for secure uploads."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.project import ProjectResponse

UploadItemStatus = Literal["pending", "uploaded", "skipped", "failed"]
UploadSessionStatus = Literal["created", "uploading", "completed"]


class UploadManifestEntryRequest(BaseModel):
    """Client-observed metadata for one file selected from a folder."""

    relative_path: str = Field(min_length=1, max_length=4096)
    size: int = Field(ge=0)


class UploadInitRequest(BaseModel):
    """Initialize an owner-scoped upload and its immutable path manifest."""

    project_name: str = Field(min_length=1, max_length=128)
    files: list[UploadManifestEntryRequest] = Field(min_length=1)

    @field_validator("project_name")
    @classmethod
    def normalize_project_name(cls, value: str) -> str:
        """Trim display-only whitespace while rejecting blank project names."""
        normalized = value.strip()
        if not normalized:
            raise ValueError("project_name must not be blank")
        return normalized


class UploadManifestItem(BaseModel):
    """Server-classified manifest entry and its upload outcome."""

    relative_path: str
    declared_size: int = Field(ge=0)
    status: UploadItemStatus
    language: Literal["java", "python"] | None = None
    reason: str | None = None
    actual_size: int | None = Field(default=None, ge=0)
    line_count: int | None = Field(default=None, ge=0)
    content_hash: str | None = None
    encoding: str | None = None


class UploadSessionResponse(BaseModel):
    """Upload progress, coverage counters, and the complete manifest."""

    model_config = ConfigDict(from_attributes=True)

    upload_id: str
    project_id: int | None
    project_name: str
    status: UploadSessionStatus
    total_files: int = Field(ge=0)
    uploaded_files: int = Field(ge=0)
    skipped_files: int = Field(ge=0)
    failed_files: int = Field(ge=0)
    total_size: int = Field(ge=0)
    uploaded_size: int = Field(ge=0)
    manifest: list[UploadManifestItem]
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class UploadCompleteResponse(BaseModel):
    """Completed upload plus the project created from accepted files."""

    upload: UploadSessionResponse
    project: ProjectResponse
