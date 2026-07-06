"""Reviewer agent — identifies issues from retrieved context per spec §12.1, §14.2."""

from __future__ import annotations

import logging
from typing import Any

from app.agents.prompts.templates import build_reviewer_messages
from app.agents.usage import build_failed_usage_update, build_usage_update
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
            retry_issues=state.retry_issues,
        )

        output: ReviewOutput
        result: LLMCallResult
        try:
            output, result = await self._llm.invoke(messages, ReviewOutput)
        except Exception as exc:
            logger.error("reviewer_failed", extra={"error": str(exc)[:256]})
            return {
                "current_issues": [],
                "current_item_warning": "reviewer_error",
                "next_action": "review_decision",
                **build_failed_usage_update(state, exc),
            }

        issues: list[dict[str, Any]] = []
        for issue in output.issues:
            d = issue.model_dump()
            d["review_round"] = state.review_round
            issues.append(d)
        if state.retry_issues:
            allowed = {
                (str(issue.get("relative_path", "")), str(issue.get("rule_id", "")))
                for issue in state.retry_issues
            }
            issues = [
                issue
                for issue in issues
                if (str(issue.get("relative_path", "")), str(issue.get("rule_id", ""))) in allowed
            ]

        warning: str | None = None
        if not issues and not context:
            warning = "insufficient_context"

        return {
            "current_issues": issues,
            "current_item_warning": warning,
            "next_action": "review_decision",
            **build_usage_update(state, result),
        }
