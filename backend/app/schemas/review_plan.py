"""Review plan schemas per spec §14.1.

Planner agent emits a bounded review plan that drives the entire
Agent workflow (InitItem → Retrieve → Review → EvidenceVerify → Critic).
"""

from typing import Literal

from pydantic import BaseModel, Field


class ReviewItem(BaseModel):
    """One review target in the plan — a file, path set, or module."""

    key: str
    review_type: str
    target_paths: list[str]
    keywords: list[str]
    risk_focus: list[str]
    priority: Literal["high", "medium", "low"]
    top_k: int = Field(default=10, ge=1, le=30)


class ReviewPlan(BaseModel):
    """Bounded review plan with at most 10 items."""

    items: list[ReviewItem] = Field(max_length=10)
