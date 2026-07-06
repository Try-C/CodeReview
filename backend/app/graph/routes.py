"""Conditional edge routing functions per spec §12.8.

Every route is a pure function that reads only ``state.next_action``.
No route modifies state or accesses external services.
"""

from __future__ import annotations

from typing import Any

# Route destination constants — the next node names in the compiled graph.
ROUTE_REPORT = "report"
ROUTE_GUARD_RETRIEVE = "guard_retrieve"
ROUTE_EVIDENCE_VERIFY = "evidence_verify"
ROUTE_ADVANCE_ITEM = "advance_item"
ROUTE_REVIEW_DECISION = "review_decision"


def route_guard_planner(state: dict[str, Any] | object) -> str:
    """GuardPlanner → proceed to planner or short-circuit to report."""
    na = _next_action(state)
    if na == "report":
        return ROUTE_REPORT
    return "planner"


def route_guard_retrieve(state: dict[str, Any] | object) -> str:
    """GuardRetrieve → retrieve or report."""
    na = _next_action(state)
    if na == "report":
        return ROUTE_REPORT
    return "retrieve"


def route_guard_review(state: dict[str, Any] | object) -> str:
    """GuardReview → review or report."""
    na = _next_action(state)
    if na == "report":
        return ROUTE_REPORT
    return "review"


def route_review_decision(state: dict[str, Any] | object) -> str:
    """ReviewDecision: no issues → advance, context low → rewrite, issues → evidence."""
    na = _next_action(state)
    if na == "advance_item":
        return ROUTE_ADVANCE_ITEM
    if na == "rewrite_query":
        return "rewrite_query"
    return ROUTE_EVIDENCE_VERIFY


def route_rewrite_query(state: dict[str, Any] | object) -> str:
    """RewriteQuery: retry → GuardRetrieve, exhausted → AdvanceItem."""
    na = _next_action(state)
    if na == "advance_item":
        return ROUTE_ADVANCE_ITEM
    return ROUTE_GUARD_RETRIEVE


def route_evidence_decision(state: dict[str, Any] | object) -> str:
    """EvidenceDecision: no valid issues → advance, valid → GuardCritic."""
    na = _next_action(state)
    if na == "advance_item":
        return ROUTE_ADVANCE_ITEM
    return "guard_critic"


def route_guard_critic(state: dict[str, Any] | object) -> str:
    """GuardCritic → critic or report."""
    na = _next_action(state)
    if na == "report":
        return ROUTE_REPORT
    return "critic"


def route_critic_decision(state: dict[str, Any] | object) -> str:
    """CriticDecision: failed & can re-review → GuardReview, else → AdvanceItem."""
    na = _next_action(state)
    if na == "prepare_rereview":
        return ROUTE_GUARD_RETRIEVE
    return ROUTE_ADVANCE_ITEM


def route_advance_item(state: dict[str, Any] | object) -> str:
    """AdvanceItem: more items → InitItem, done → Report."""
    na = _next_action(state)
    if na == "init_item":
        return "init_item"
    return ROUTE_REPORT


def _next_action(state: dict[str, Any] | object) -> str:
    """Extract next_action from either a dict or a Pydantic model."""
    if isinstance(state, dict):
        return str(state.get("next_action", ""))
    return str(getattr(state, "next_action", ""))
