"""LangGraph review-graph builder per spec §12.3 workflow.

Compiles the full pipeline once and reuses it across tasks.
Agents and deterministic nodes are injected at build time.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from langgraph.errors import GraphRecursionError
from langgraph.graph import END, StateGraph

from app.core.config import get_settings
from app.graph.nodes import (
    AdvanceItemNode,
    BudgetGuardNode,
    CriticDecisionNode,
    EvidenceDecisionNode,
    EvidenceVerifyNode,
    FinalizeItemNode,
    InitItemNode,
    PrepareRereviewNode,
    ReportNode,
    RetrieveNode,
    ReviewDecisionNode,
    RewriteQueryNode,
)
from app.graph.routes import (
    route_advance_item,
    route_critic_decision,
    route_evidence_decision,
    route_guard_critic,
    route_guard_planner,
    route_guard_retrieve,
    route_guard_review,
    route_review_decision,
    route_rewrite_query,
)
from app.graph.state import CodeReviewState

logger = logging.getLogger(__name__)


def build_review_graph(
    *,
    planner_node: Callable[..., Any],
    reviewer_node: Callable[..., Any],
    critic_node: Callable[..., Any],
    file_scan_node: Callable[..., Any] | None = None,
    code_parse_node: Callable[..., Any] | None = None,
    index_build_node: Callable[..., Any] | None = None,
    retrieve_fn: Callable[..., Any] | None = None,
    evidence_verify_fn: Callable[..., Any] | None = None,
    report_node: Callable[..., Any] | None = None,
) -> Any:  # CompiledStateGraph
    """Build and compile the full review graph per §12.3.

    All agent and service nodes are injected so that tests can substitute
    fake implementations.  The compiled graph is stateless and reusable.
    """
    builder = StateGraph(CodeReviewState)

    # ── Guard instances (§12.4) ──────────────────────────────────────────
    guard_planner = BudgetGuardNode("planner")
    guard_retrieve = BudgetGuardNode("retrieve")
    guard_review = BudgetGuardNode("review")
    guard_critic = BudgetGuardNode("critic")

    # ── Deterministic nodes ──────────────────────────────────────────────
    init_item = InitItemNode()
    review_decision = ReviewDecisionNode()
    rewrite_query = RewriteQueryNode()
    evidence_decision = EvidenceDecisionNode()
    critic_decision = CriticDecisionNode()
    prepare_rereview = PrepareRereviewNode()
    finalize_item = FinalizeItemNode()
    advance_item = AdvanceItemNode()
    report = report_node if report_node is not None else ReportNode()

    # Agent nodes are injected; deterministic fallbacks for non-injected ones.
    _planner = planner_node
    _reviewer = reviewer_node
    _critic = critic_node

    # ── Add nodes ────────────────────────────────────────────────────────
    builder.add_node("guard_planner", guard_planner)
    builder.add_node("planner", _planner)
    builder.add_node("init_item", init_item)
    builder.add_node("guard_retrieve", guard_retrieve)
    builder.add_node("guard_review", guard_review)
    builder.add_node("guard_critic", guard_critic)
    builder.add_node("review_decision", review_decision)
    builder.add_node("rewrite_query", rewrite_query)
    builder.add_node("evidence_decision", evidence_decision)
    builder.add_node("critic_decision", critic_decision)
    builder.add_node("prepare_rereview", prepare_rereview)
    builder.add_node("finalize_item", finalize_item)
    builder.add_node("advance_item", advance_item)
    builder.add_node("report", report)

    # Agent nodes.
    builder.add_node("review", _reviewer)
    builder.add_node("critic", _critic)

    # File-scan / parse / index chain (pre-existing services).
    if file_scan_node:
        builder.add_node("file_scan", file_scan_node)
    if code_parse_node:
        builder.add_node("code_parse", code_parse_node)
    if index_build_node:
        builder.add_node("index_build", index_build_node)

    # Retrieve (injected or no-op).
    retrieve_node_fn: Callable[..., Any]
    if retrieve_fn:
        retrieve_node_fn = RetrieveNode(retrieve_fn)
    else:

        async def _noop_retrieve(state: CodeReviewState) -> dict[str, Any]:
            return {"retrieved_context": "", "next_action": "guard_review"}

        retrieve_node_fn = _noop_retrieve
    builder.add_node("retrieve", retrieve_node_fn)

    # Evidence verify.
    evidence_verify_fn_node: Callable[..., Any]
    if evidence_verify_fn:
        evidence_verify_fn_node = EvidenceVerifyNode(evidence_verify_fn)
    else:

        async def _noop_evidence(state: CodeReviewState) -> dict[str, Any]:
            passed = [
                {**i, "evidence_status": "passed"}
                for i in state.current_issues
            ]
            na = "guard_critic" if passed else "advance_item"
            return {"current_issues": passed, "next_action": na}

        evidence_verify_fn_node = _noop_evidence
    builder.add_node("evidence_verify", evidence_verify_fn_node)

    # ── Entry point ──────────────────────────────────────────────────────
    # For M10, the pipeline starts at FileScan (or Planner if scans are done).
    has_scan = bool(file_scan_node and code_parse_node and index_build_node)
    if has_scan:
        builder.set_entry_point("file_scan")
        builder.add_edge("file_scan", "code_parse")
        builder.add_edge("code_parse", "index_build")
        builder.add_edge("index_build", "guard_planner")
    else:
        builder.set_entry_point("guard_planner")

    # ── Edges ────────────────────────────────────────────────────────────

    # GuardPlanner → Planner | Report
    builder.add_conditional_edges("guard_planner", route_guard_planner, {
        "planner": "planner",
        "report": "report",
    })

    # Planner → InitItem (always)
    builder.add_edge("planner", "init_item")

    # InitItem → GuardRetrieve
    builder.add_edge("init_item", "guard_retrieve")

    # GuardRetrieve → Retrieve | Report
    builder.add_conditional_edges("guard_retrieve", route_guard_retrieve, {
        "retrieve": "retrieve",
        "report": "report",
    })

    # Retrieve → GuardReview
    builder.add_edge("retrieve", "guard_review")

    # GuardReview → Review | Report
    builder.add_conditional_edges("guard_review", route_guard_review, {
        "review": "review",
        "report": "report",
    })

    # Review → ReviewDecision
    builder.add_edge("review", "review_decision")

    # ReviewDecision → AdvanceItem | RewriteQuery | EvidenceVerify
    builder.add_conditional_edges("review_decision", route_review_decision, {
        "advance_item": "advance_item",
        "rewrite_query": "rewrite_query",
        "evidence_verify": "evidence_verify",
    })

    # RewriteQuery → GuardRetrieve | AdvanceItem
    builder.add_conditional_edges("rewrite_query", route_rewrite_query, {
        "guard_retrieve": "guard_retrieve",
        "advance_item": "advance_item",
    })

    # EvidenceVerify → EvidenceDecision
    builder.add_edge("evidence_verify", "evidence_decision")

    # EvidenceDecision → AdvanceItem | GuardCritic
    builder.add_conditional_edges("evidence_decision", route_evidence_decision, {
        "advance_item": "advance_item",
        "guard_critic": "guard_critic",
    })

    # GuardCritic → Critic | Report
    builder.add_conditional_edges("guard_critic", route_guard_critic, {
        "critic": "critic",
        "report": "report",
    })

    # Critic → CriticDecision
    builder.add_edge("critic", "critic_decision")

    # CriticDecision → PrepareRereview | AdvanceItem
    builder.add_conditional_edges("critic_decision", route_critic_decision, {
        "guard_retrieve": "guard_retrieve",
        "advance_item": "advance_item",
    })

    # PrepareRereview → GuardReview
    builder.add_edge("prepare_rereview", "guard_review")

    # FinalizeItem → AdvanceItem
    builder.add_edge("finalize_item", "advance_item")

    # AdvanceItem → InitItem | Report
    builder.add_conditional_edges("advance_item", route_advance_item, {
        "init_item": "init_item",
        "report": "report",
    })

    # Report → END
    builder.add_edge("report", END)

    return builder.compile()


async def invoke_graph(
    graph: Any,  # CompiledStateGraph
    initial_state: dict[str, Any],
    *,
    recursion_limit: int | None = None,
) -> dict[str, Any]:
    """Invoke the compiled graph with recursion-limit guarding (§12.4)."""
    settings = get_settings()
    limit = recursion_limit if recursion_limit is not None else settings.langgraph_recursion_limit
    try:
        result: dict[str, Any] = await graph.ainvoke(
            initial_state,
            config={"recursion_limit": limit},
        )
        return result
    except GraphRecursionError:
        logger.error("graph_recursion_limit_exceeded")
        return {
            **initial_state,
            "next_action": "done",
            "stop_reason": "graph_recursion_limit_exceeded",
            "error_message": "Graph recursion limit exceeded — partial results saved.",
        }
