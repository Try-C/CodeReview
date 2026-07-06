"""Review plan schemas per spec §14.1.

Planner agent emits a bounded review plan that drives the entire
Agent workflow (InitItem → Retrieve → Review → EvidenceVerify → Critic).

Field validators coerce string → list so the schema is tolerant of
LLMs that return a single string instead of a list for array fields.
"""

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


def _coerce_str_to_list(value: Any) -> list[str]:
    """Accept a single string and wrap it in a list; pass lists through."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return value
    raise ValueError(f"Expected string or list, got {type(value).__name__}")


class ReviewItem(BaseModel):
    """One review target in the plan — a file, path set, or module."""

    key: str
    review_type: str
    target_paths: list[str]
    keywords: list[str]
    risk_focus: list[str]
    priority: Literal["high", "medium", "low"]
    top_k: int = Field(default=10, ge=1, le=30)

    @field_validator("target_paths", "keywords", "risk_focus", mode="before")
    @classmethod
    def _list_coercion(cls, v: Any) -> list[str]:
        return _coerce_str_to_list(v)


class ReviewPlan(BaseModel):
    """Bounded review plan with at most 10 items."""

    items: list[ReviewItem] = Field(max_length=10)
