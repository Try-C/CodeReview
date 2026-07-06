"""Reviewer agent — identifies issues from retrieved context per spec §12.1, §14.2."""

from __future__ import annotations

import logging
from typing import Any

from app.agents.prompts.templates import build_reviewer_messages
from app.graph.state import CodeReviewState
from app.llm.structured import StructuredLLM
from app.llm.usage import LLMCallResult
from app.schemas.issue import ReviewOutput

logger = logging.getLogger(__name__)


class ReviewerAgent:
    """Call the LLM to review assembled context and produce IssueCandidates."""

    def __init__(self, llm: StructuredLLM) -> None:
        self._llm = llm

    async def __call__(self, state: CodeReviewState) -> dict[str, Any]:
        item = state.current_review_item or {}
        context = state.retrieved_context or ""

        messages = build_reviewer_messages(
            review_item=item,
            retrieved_context=context,
            critic_feedback=state.critic_feedback,
        )

        output: ReviewOutput
        result: LLMCallResult
        try:
            output, result = await self._llm.invoke(messages, ReviewOutput)
        except Exception as exc:
            logger.error("reviewer_failed", extra={"error": str(exc)[:256]})
            return {
                "current_issues": [],
                "llm_call_count": state.llm_call_count + 1,
                "input_tokens": state.input_tokens,
                "output_tokens": state.output_tokens,
                "current_item_warning": "reviewer_error",
                "next_action": "review_decision",
            }

        issues: list[dict[str, Any]] = []
        for issue in output.issues:
            d = issue.model_dump()
            issues.append(d)

        warning: str | None = None
        if not issues and not context:
            warning = "insufficient_context"

        return {
            "current_issues": issues,
            "llm_call_count": state.llm_call_count + 1,
            "input_tokens": state.input_tokens + result.input_tokens,
            "output_tokens": state.output_tokens + result.output_tokens,
            "current_item_warning": warning,
            "next_action": "review_decision",
        }
