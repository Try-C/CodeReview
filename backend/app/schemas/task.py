"""Request and response contracts for asynchronous review tasks."""

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ReviewMode = Literal["security", "bug", "performance", "maintainability", "comprehensive"]
TaskStatus = Literal[
    "pending",
    "scanning",
    "parsing",
    "indexing",
    "planning",
    "reviewing",
    "verifying",
    "reporting",
    "success",
    "partial_success",
    "failed",
    "cancel_requested",
    "cancelled",
]
TERMINAL_TASK_STATUSES = frozenset({"success", "partial_success", "failed", "cancelled"})


class ReviewCreateRequest(BaseModel):
    """Create-or-return-one task under an owner-scoped idempotency key."""

    idempotency_key: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")
    review_mode: ReviewMode = "security"


class ReviewTaskResponse(BaseModel):
    """Public task state without internal retry or broker details."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    status: TaskStatus
    review_mode: ReviewMode
    current_stage: str | None
    progress: int
    llm_call_count: int
    input_tokens: int
    output_tokens: int
    estimated_cost: Decimal | None
    cost_status: Literal["available", "unavailable", "partial"]
    cancel_requested: bool
    error_code: str | None
    error_message: str | None
    fallback_reason: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime


class TaskEventResponse(BaseModel):
    """Durable event contract used by JSON APIs and SSE payloads."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: int
    event_type: str
    stage: str | None
    progress: int | None
    message: str | None
    metadata: dict[str, object] | None = Field(validation_alias="metadata_")
    created_at: datetime
