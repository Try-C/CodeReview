"""Health endpoint response schemas."""

from typing import Literal

from pydantic import BaseModel


class LiveHealthResponse(BaseModel):
    """Process liveness response."""

    status: Literal["ok"] = "ok"
    service: str
    version: str


class ReadyHealthResponse(BaseModel):
    """Application readiness response."""

    status: Literal["ready"] = "ready"
    service: str
    version: str
    checks: dict[str, Literal["ok"]]
