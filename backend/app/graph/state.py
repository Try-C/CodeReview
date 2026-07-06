"""CodeReviewState — canonical LangGraph state per spec §12.2.

Holds only serialisable objects; no DB sessions, client instances, or raw
repository source.  All fields use default factories so the graph can build
an initial state from a plain dict.
"""

from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field


class CodeReviewState(BaseModel):
    """Serialisable state passed through every node in the review graph."""

    task_id: int
    project_id: int
    user_id: int
    project_root: str

    file_summary: dict[str, Any] = Field(default_factory=dict)
    review_plan: list[dict[str, Any]] = Field(default_factory=list)
    current_review_index: int = 0

    verified_issues: list[dict[str, Any]] = Field(default_factory=list)
    rejected_issues: list[dict[str, Any]] = Field(default_factory=list)

    current_review_item: dict[str, Any] | None = None
    current_issues: list[dict[str, Any]] = Field(default_factory=list)
    retry_issues: list[dict[str, Any]] = Field(default_factory=list)
    critic_decisions: list[dict[str, Any]] = Field(default_factory=list)

    retrieved_chunks: list[dict[str, Any]] = Field(default_factory=list)
    retrieved_context: str = ""
    retrieval_query: str = ""
    retrieval_target_paths: list[str] = Field(default_factory=list)
    retrieval_top_k: int = 10
    retrieval_retry_count: int = 0
    last_retrieved_chunk_ids: list[int] = Field(default_factory=list)
    critic_feedback: str | None = None

    review_round: int = 1
    max_review_rounds: int = 2
    llm_call_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost: Decimal | None = None
    cost_status: str = "unavailable"
    last_usage: dict[str, Any] = Field(default_factory=dict)

    next_action: str = "init_item"
    current_item_warning: str | None = None
    stop_reason: str | None = None
    cancel_requested: bool = False

    coverage_summary: dict[str, Any] = Field(default_factory=dict)
    error_message: str | None = None
