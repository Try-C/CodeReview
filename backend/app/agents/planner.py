"""Planner agent — generates a bounded review plan per spec §12.1 and §14.1."""

from __future__ import annotations

import logging
from typing import Any

from app.agents.prompts.templates import build_planner_messages
from app.agents.usage import build_failed_usage_update, build_usage_update
from app.graph.state import CodeReviewState
from app.llm.structured import StructuredLLM
from app.llm.usage import LLMCallResult
from app.schemas.review_plan import ReviewPlan

logger = logging.getLogger(__name__)


class PlannerAgent:
    """Call the LLM to produce a ReviewPlan from the project's file summary."""

    def __init__(self, llm: StructuredLLM) -> None:
        self._llm = llm

    async def __call__(self, state: CodeReviewState) -> dict[str, Any]:
        messages = build_planner_messages(state.file_summary)

        plan: ReviewPlan
        result: LLMCallResult
        try:
            plan, result = await self._llm.invoke(messages, ReviewPlan)
        except Exception as exc:
            logger.error("planner_failed", extra={"error": str(exc)[:256]})
            return {
                "review_plan": [],
                "next_action": "report",
                "error_message": "Planner failed",
                "stop_reason": "planner_failed",
                **build_failed_usage_update(state, exc),
            }

        items = [item.model_dump() for item in plan.items]

        return {
            "review_plan": items,
            "next_action": "init_item",
            **build_usage_update(state, result),
        }
