"""Shared state updates for validated LLM call accounting."""

from decimal import Decimal
from typing import Any

from app.graph.state import CodeReviewState
from app.llm.usage import LLMCallResult


def build_usage_update(
    state: CodeReviewState,
    result: LLMCallResult,
) -> dict[str, Any]:
    """Return cumulative counters plus the latest immutable pricing snapshot."""
    previous_has_cost = state.estimated_cost is not None
    current_has_cost = result.cost_status == "available" and result.estimated_cost is not None
    estimated_cost: Decimal | None = state.estimated_cost
    if current_has_cost:
        current_cost = result.estimated_cost
        assert current_cost is not None
        estimated_cost = (estimated_cost or Decimal("0")) + current_cost

    if current_has_cost and (state.llm_call_count == 0 or state.cost_status == "available"):
        cost_status = "available"
    elif previous_has_cost or current_has_cost:
        cost_status = "partial"
    else:
        cost_status = "unavailable"

    return {
        "llm_call_count": state.llm_call_count + result.call_count,
        "input_tokens": state.input_tokens + result.input_tokens,
        "output_tokens": state.output_tokens + result.output_tokens,
        "estimated_cost": estimated_cost,
        "cost_status": cost_status,
        "last_usage": result.model_dump(mode="json"),
    }


def build_failed_usage_update(
    state: CodeReviewState,
    error: Exception,
) -> dict[str, Any]:
    """Account for provider work completed before a node-level failure."""
    result = getattr(error, "result", None)
    if isinstance(result, LLMCallResult):
        return build_usage_update(state, result)
    return {"llm_call_count": state.llm_call_count + 1}
