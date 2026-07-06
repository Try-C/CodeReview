"""Graph node implementations per spec §12.3 and §12.4.

Each node receives CodeReviewState and returns a dict of partial state updates.
Agent nodes (Planner, Reviewer, Critic) are injected through their constructors;
deterministic nodes live here.

BudgetGuard (§12.4) checks four conditions before allowing an LLM call:
    cancel_requested | stop_reason | llm_call_count >= max_calls | tokens >= budget
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from app.core.config import get_settings
from app.graph.state import CodeReviewState

logger = logging.getLogger(__name__)

# ── BudgetGuard (§12.4) ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class BudgetGuardNode:
    """Guard that blocks progression when budget / cancel thresholds are met.

    Four instances are created:
        GuardPlanner  = BudgetGuardNode("planner")
        GuardRetrieve = BudgetGuardNode("retrieve")
        GuardReview   = BudgetGuardNode("review")
        GuardCritic   = BudgetGuardNode("critic")

    The *proceed_action* is the next_action value set when the guard passes.
    On failure the node sets next_action="report" with a stop_reason.
    """

    proceed_action: str

    def __call__(self, state: CodeReviewState) -> dict[str, Any]:
        settings = get_settings()
        checks: list[tuple[bool, str]] = [
            (state.cancel_requested, "cancel_requested"),
            (state.stop_reason is not None, "stop_reason_set"),
            (state.llm_call_count >= settings.max_llm_calls, "llm_call_limit_exceeded"),
            (
                state.input_tokens + state.output_tokens >= settings.max_token_budget,
                "token_budget_exceeded",
            ),
        ]
        for triggered, reason in checks:
            if triggered:
                logger.info(
                    "budget_guard_blocked",
                    extra={
                        "guard": self.proceed_action,
                        "reason": reason,
                        "llm_calls": state.llm_call_count,
                        "tokens": state.input_tokens + state.output_tokens,
                    },
                )
                return {
                    "next_action": "report",
                    "stop_reason": f"budget_guard_{reason}",
                    "fallback_reason": reason,
                }
        return {"next_action": self.proceed_action}


# ── InitItem ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class InitItemNode:
    """Load the next review plan item into current_review_item.

    If the plan is empty or exhausted, routes to report via next_action.
    """

    def __call__(self, state: CodeReviewState) -> dict[str, Any]:
        if state.current_review_index >= len(state.review_plan):
            return {"next_action": "report"}
        item = state.review_plan[state.current_review_index]
        return {
            "current_review_item": item,
            "current_issues": [],
            "retry_issues": [],
            "retrieved_chunks": [],
            "retrieved_context": "",
            "retrieval_query": "",
            "retrieval_retry_count": 0,
            "critic_feedback": None,
            "current_item_warning": None,
            "next_action": "guard_retrieve",
        }


# ── Retrieve ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class RetrieveNode:
    """Call HybridRetriever and store the assembled context.

    The retriever is injected so tests can use a fake.
    """

    retrieve_fn: Callable[..., Any]

    async def __call__(self, state: CodeReviewState) -> dict[str, Any]:
        item = state.current_review_item or {}
        query = state.retrieval_query or " ".join(item.get("keywords", []))
        # paths and top_k from state are currently passed through retriever config.

        try:
            result = await self.retrieve_fn(
                task_id=state.task_id,
                project_id=state.project_id,
                query=query,
                languages=("java", "python"),
                review_item_key=item.get("key", ""),
                retrieval_round=state.retrieval_retry_count + 1,
            )
        except Exception as exc:
            logger.warning("retrieve_node_failed", extra={"error": str(exc)[:128]})
            return {
                "retrieved_context": "",
                "retrieved_chunks": [],
                "current_item_warning": "retrieval_failed",
                "next_action": "guard_review",
            }

        context = result.get("context", "") if isinstance(result, dict) else ""
        chunks = result.get("chunks", []) if isinstance(result, dict) else []

        return {
            "retrieved_context": str(context),
            "retrieved_chunks": list(chunks),
            "next_action": "guard_review",
        }


# ── ReviewDecision ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ReviewDecisionNode:
    """Route after Review: no issues → advance, low context → rewrite, issues → verify."""

    def __call__(self, state: CodeReviewState) -> dict[str, Any]:
        issues = state.current_issues
        warning = state.current_item_warning or ""

        if warning == "insufficient_context":
            if state.retrieval_retry_count < 2:
                return {"next_action": "rewrite_query"}
            return {
                "current_item_warning": "insufficient_context_exhausted",
                "next_action": "advance_item",
            }

        if not issues:
            return {"next_action": "advance_item"}

        return {"next_action": "evidence_verify"}


# ── RewriteQuery (§12.6) ────────────────────────────────────────────────────


@dataclass(frozen=True)
class RewriteQueryNode:
    """Rewrite the retrieval query when context was insufficient.

    retry 0 → rewrite query based on review target and missing context
    retry 1 → expand paths and supplement symbol neighbours
    retry >= 2 → advance_item (handled by ReviewDecision before reaching here)
    """

    def __call__(self, state: CodeReviewState) -> dict[str, Any]:
        item = state.current_review_item or {}
        attempt = state.retrieval_retry_count

        if attempt == 0:
            keywords = item.get("keywords", [])
            risk = item.get("risk_focus", [])
            expanded = " ".join(keywords + risk) or state.retrieval_query
            return {
                "retrieval_query": expanded,
                "retrieval_retry_count": attempt + 1,
                "current_item_warning": None,
                "next_action": "guard_retrieve",
            }

        # attempt 1: expand paths + neighbours
        paths: list[str] = list(item.get("target_paths", []))
        return {
            "retrieval_query": state.retrieval_query,
            "retrieval_target_paths": paths,
            "retrieval_retry_count": attempt + 1,
            "current_item_warning": None,
            "next_action": "guard_retrieve",
        }


# ── EvidenceVerify + EvidenceDecision ──────────────────────────────────────


@dataclass(frozen=True)
class EvidenceVerifyNode:
    """Run the four EvidenceService checks on every current issue (§13).

    The verify_fn is injected — typically EvidenceService.verify_one.
    """

    verify_fn: Callable[..., Awaitable[dict[str, Any]]]

    async def __call__(self, state: CodeReviewState) -> dict[str, Any]:
        verified: list[dict[str, Any]] = []
        for issue in state.current_issues:
            try:
                result = await self.verify_fn(
                    issue=issue,
                    project_id=state.project_id,
                    project_root=state.project_root,
                )
                verified.append(result)
            except Exception as exc:
                logger.warning("evidence_verify_error", extra={"error": str(exc)[:128]})
                issue_copy = dict(issue)
                issue_copy["evidence_status"] = "error"
                issue_copy["evidence_checks"] = {"error": str(exc)}
                verified.append(issue_copy)

        # Split: passed vs failed.
        passed = [i for i in verified if i.get("evidence_status") == "passed"]

        update: dict[str, Any] = {"current_issues": verified}
        if not passed:
            update["next_action"] = "advance_item"
        else:
            update["current_issues"] = passed
            update["next_action"] = "guard_critic"
        return update


@dataclass(frozen=True)
class EvidenceDecisionNode:
    """Deterministic post-evidence decision. (Kept as separate node for traceability.)"""

    def __call__(self, state: CodeReviewState) -> dict[str, Any]:
        if not state.current_issues:
            return {"next_action": "advance_item"}
        return {"next_action": "guard_critic"}


# ── CriticDecision (§12.7) ─────────────────────────────────────────────────


@dataclass(frozen=True)
class CriticDecisionNode:
    """Merge critic decisions into issues and split pass/fail/uncertain.

    §12.7: pass + uncertain → verified_issues (deduped by fingerprint).
           fail → retry_issues for re-review if rounds remain.
    """

    def __call__(self, state: CodeReviewState) -> dict[str, Any]:
        decisions = {d.get("fingerprint", ""): d for d in state.critic_decisions}
        passed: list[dict[str, Any]] = []
        failed: list[dict[str, Any]] = []

        for issue in state.current_issues:
            fp = issue.get("fingerprint", "")
            dec = decisions.get(fp, {})
            decision = dec.get("decision", "uncertain")

            merged = dict(issue)
            merged["critic_decision"] = decision
            merged["critic_reason"] = dec.get("reason", "")
            if dec.get("adjusted_risk_level"):
                merged["risk_level"] = dec["adjusted_risk_level"]

            if decision in ("pass", "uncertain"):
                if decision == "uncertain":
                    merged["needs_human_review"] = True
                passed.append(merged)
            else:
                failed.append(merged)

        # Merge passed into verified_issues (dedup by fingerprint).
        verified = _append_unique(state.verified_issues, passed)

        has_failures = bool(failed)
        can_retry = state.review_round < state.max_review_rounds

        if has_failures and can_retry:
            return {
                "verified_issues": verified,
                "retry_issues": failed,
                "critic_feedback": _build_feedback(failed),
                "review_round": state.review_round + 1,
                "next_action": "prepare_rereview",
            }

        # No retries left or no failures → finalize.
        rejected = state.rejected_issues + (failed if not can_retry else [])
        return {
            "verified_issues": verified,
            "rejected_issues": rejected,
            "retry_issues": [],
            "next_action": "finalize_item",
        }


# ── PrepareRereview ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PrepareRereviewNode:
    """Prepare for re-review of failed items (Critic fail → redo Review).

    Per §12.7: Critic re-review uses existing context + critic feedback,
    does NOT consume retrieval retries.
    """

    def __call__(self, state: CodeReviewState) -> dict[str, Any]:
        return {
            "current_issues": [],
            "critic_decisions": [],
            "retrieval_retry_count": state.retrieval_retry_count,
            "next_action": "guard_review",
        }


# ── FinalizeItem ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class FinalizeItemNode:
    """Mark the current review item as complete."""

    def __call__(self, state: CodeReviewState) -> dict[str, Any]:
        return {"next_action": "advance_item"}


# ── AdvanceItem ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class AdvanceItemNode:
    """Move to the next review plan item or finish."""

    def __call__(self, state: CodeReviewState) -> dict[str, Any]:
        next_idx = state.current_review_index + 1
        if next_idx >= len(state.review_plan):
            return {"next_action": "report"}
        return {
            "current_review_index": next_idx,
            "current_review_item": None,
            "current_issues": [],
            "retry_issues": [],
            "critic_decisions": [],
            "next_action": "init_item",
        }


# ── Report ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ReportNode:
    """Generate the final report (delegates to ReportService in M11).

    For M10 this produces a minimal summary so the graph can terminate.
    """

    def __call__(self, state: CodeReviewState) -> dict[str, Any]:
        return {
            "next_action": "done",
            "coverage_summary": {
                "total_plan_items": len(state.review_plan),
                "verified_issues": len(state.verified_issues),
                "rejected_issues": len(state.rejected_issues),
                "stop_reason": state.stop_reason,
            },
        }


# ── Helpers ─────────────────────────────────────────────────────────────────


def _append_unique(
    existing: list[dict[str, Any]],
    incoming: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Dedup by fingerprint — §12.7."""
    merged: dict[str, dict[str, Any]] = {x.get("fingerprint", ""): x for x in existing}
    for item in incoming:
        fp = item.get("fingerprint", "")
        if fp:
            merged[fp] = item
    return list(merged.values())


def _build_feedback(failed: list[dict[str, Any]]) -> str:
    """Build critic feedback string for the re-review prompt."""
    lines: list[str] = []
    for item in failed:
        lines.append(
            f"- [{item.get('rule_id', '?')}] {item.get('title', 'untitled')}: "
            f"{item.get('critic_reason', 'needs revision')}"
        )
    return "\n".join(lines) if lines else ""
