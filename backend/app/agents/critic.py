"""Critic agent — semantic review after evidence verification per §12.7, §14.3."""

from __future__ import annotations

import logging
from typing import Any

from app.agents.prompts.templates import build_critic_messages
from app.agents.usage import build_failed_usage_update, build_usage_update
from app.graph.state import CodeReviewState
from app.llm.structured import StructuredLLM
from app.llm.usage import LLMCallResult
from app.schemas.issue import CriticOutput

logger = logging.getLogger(__name__)


class CriticAgent:
    """Call the LLM to semantically review evidence-verified issues."""

    def __init__(self, llm: StructuredLLM) -> None:
        self._llm = llm

    async def __call__(self, state: CodeReviewState) -> dict[str, Any]:
        if not state.current_issues:
            return {
                "critic_decisions": [],
                "next_action": "critic_decision",
            }

        messages = build_critic_messages(
            issues=state.current_issues,
            retrieved_context=state.retrieved_context,
        )

        output: CriticOutput
        result: LLMCallResult
        try:
            output, result = await self._llm.invoke(messages, CriticOutput)
        except Exception as exc:
            logger.error("critic_failed", extra={"error": str(exc)[:256]})
            return {
                "critic_decisions": [],
                "current_item_warning": "critic_error",
                "next_action": "critic_decision",
                **build_failed_usage_update(state, exc),
            }

        decisions = [d.model_dump() for d in output.decisions]

        return {
            "critic_decisions": decisions,
            "next_action": "critic_decision",
            **build_usage_update(state, result),
        }
