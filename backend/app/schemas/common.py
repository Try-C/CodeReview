"""Schemas shared by API modules."""

from typing import Any

from pydantic import BaseModel, Field


class ErrorResponse(BaseModel):
    """Stable error envelope returned by every API endpoint."""

    code: str
    message: str
    request_id: str
    details: dict[str, Any] = Field(default_factory=dict)
