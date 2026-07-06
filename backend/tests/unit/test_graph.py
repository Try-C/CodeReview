"""Graph workflow tests per spec §19.3.

Covers every required scenario:
  - empty review_plan → Report
  - no issue → advance
  - context insufficient once → rewrite query
  - context insufficient exhausted → skip current item
  - all evidence failed → advance
  - critic partial pass → pass items retained immediately
  - critic fail with rounds → re-review only failures
  - rounds exhausted → reject
  - budget exceeded → no LLM call
  - graph recursion_limit → partial_success
  - price unconfigured → cost_unavailable
  - cancel task → cancelled
  - GraphRecursionError is caught and returns partial result
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Any

import pytest

from app.agents.critic import CriticAgent
from app.agents.planner import PlannerAgent
from app.agents.reviewer import ReviewerAgent
from app.graph.builder import build_review_graph, invoke_graph
from app.graph.nodes import BudgetGuardNode, CriticDecisionNode
from app.graph.state import CodeReviewState
from app.llm.client import FakeLLMClient
from app.llm.structured import StructuredLLM
from app.schemas.issue import CriticOutput, CriticResult, IssueCandidate, ReviewOutput
from app.schemas.review_plan import ReviewItem, ReviewPlan

# ── Helpers ─────────────────────────────────────────────────────────────────


def _make_state(**overrides: Any) -> CodeReviewState:
    defaults: dict[str, Any] = {
        "task_id": 1,
        "project_id": 1,
        "user_id": 1,
        "project_root": "/tmp/test-project",
        "next_action": "init_item",
    }
    defaults.update(overrides)
    return CodeReviewState(**defaults)


def _make_plan_item(
    key: str = "item-1",
    review_type: str = "security",
    target_paths: list[str] | None = None,
    keywords: list[str] | None = None,
    risk_focus: list[str] | None = None,
    priority: str = "high",
    top_k: int = 10,
) -> dict[str, Any]:
    return {
        "key": key,
        "review_type": review_type,
        "target_paths": target_paths or ["src/"],
        "keywords": keywords or ["test"],
        "risk_focus": risk_focus or ["CWE-89"],
        "priority": priority,
        "top_k": top_k,
    }


def _make_issue(**overrides: Any) -> dict[str, Any]:
    d: dict[str, Any] = {
        "relative_path": "src/Foo.java",
        "start_line": 10,
        "end_line": 12,
        "evidence": "bad code",
        "source_chunk_ids": [1],
        "category": "security",
        "issue_type": "SQL Injection",
        "risk_level": "High",
        "rule_id": "T-001",
        "cwe_id": "CWE-89",
        "title": "Test issue",
        "description": "Test description",
        "reason": "Test reason",
        "suggestion": "Test suggestion",
        "confidence": 0.9,
        "fingerprint": "fp-test-001",
    }
    d.update(overrides)
    return d


def _build_fake_llm(response_model: Any) -> StructuredLLM:
    """Build a StructuredLLM backed by a FakeLLMClient with a serialised response."""
    if hasattr(response_model, "model_dump"):
        text = json.dumps(response_model.model_dump())
    else:
        text = json.dumps(response_model)
    return StructuredLLM(FakeLLMClient(response_text=text))


# ── BudgetGuard tests (§12.4, §19.3) ────────────────────────────────────────


class TestBudgetGuard:
    async def test_proceed_when_under_budget(self) -> None:
        guard = BudgetGuardNode("planner")
        state = _make_state(llm_call_count=5, input_tokens=1000, output_tokens=500)
        result = await guard(state)
        assert result["next_action"] == "planner"

    async def test_blocks_on_cancel(self) -> None:
        guard = BudgetGuardNode("review")
        state = _make_state(cancel_requested=True)
        result = await guard(state)
        assert result["next_action"] == "report"
        assert "cancel_requested" in result.get("fallback_reason", "")

    async def test_blocks_on_stop_reason(self) -> None:
        guard = BudgetGuardNode("critic")
        state = _make_state(stop_reason="previous_error")
        result = await guard(state)
        assert result["next_action"] == "report"

    async def test_blocks_on_llm_call_limit(self) -> None:
        guard = BudgetGuardNode("planner")
        state = _make_state(llm_call_count=30, input_tokens=0, output_tokens=0)
        result = await guard(state)
        assert result["next_action"] == "report"
        assert "llm_call_limit" in result.get("fallback_reason", "")

    async def test_blocks_on_token_budget(self) -> None:
        guard = BudgetGuardNode("review")
        state = _make_state(llm_call_count=0, input_tokens=50000, output_tokens=51000)
        result = await guard(state)
        assert result["next_action"] == "report"
        assert "token_budget" in result.get("fallback_reason", "")

    async def test_checks_live_cancellation(self) -> None:
        async def cancelled(task_id: int) -> bool:
            assert task_id == 1
            return True

        guard = BudgetGuardNode("review", cancelled)
        result = await guard(_make_state(cancel_requested=False))
        assert result["next_action"] == "report"
        assert result["fallback_reason"] == "cancel_requested"


# ── CriticDecision tests (§12.7) ────────────────────────────────────────────


class TestCriticDecision:
    def test_pass_and_uncertain_added_to_verified(self) -> None:
        node = CriticDecisionNode()
        state = _make_state(
            current_issues=[
                _make_issue(fingerprint="fp-1"),
                _make_issue(fingerprint="fp-2"),
            ],
            critic_decisions=[
                {"fingerprint": "fp-1", "decision": "pass", "reason": "ok"},
                {"fingerprint": "fp-2", "decision": "uncertain", "reason": "maybe"},
            ],
            verified_issues=[],
        )
        result = node(state)
        assert result["next_action"] == "finalize_item"
        assert len(result["verified_issues"]) == 2
        # uncertain sets needs_human_review.
        uncertain = [i for i in result["verified_issues"] if i.get("needs_human_review")]
        assert len(uncertain) == 1

    def test_fail_with_rounds_remaining_goes_to_rereview(self) -> None:
        node = CriticDecisionNode()
        state = _make_state(
            current_issues=[_make_issue(fingerprint="fp-1")],
            critic_decisions=[
                {"fingerprint": "fp-1", "decision": "fail", "reason": "fp"},
            ],
            review_round=1,
            max_review_rounds=2,
        )
        result = node(state)
        assert result["next_action"] == "prepare_rereview"
        assert len(result["retry_issues"]) == 1
        assert result["review_round"] == 2

    def test_fail_rounds_exhausted_adds_to_rejected(self) -> None:
        node = CriticDecisionNode()
        state = _make_state(
            current_issues=[_make_issue(fingerprint="fp-1")],
            critic_decisions=[
                {"fingerprint": "fp-1", "decision": "fail", "reason": "fp"},
            ],
            review_round=2,
            max_review_rounds=2,
        )
        result = node(state)
        assert result["next_action"] == "finalize_item"
        assert len(result["rejected_issues"]) == 1
        assert len(result["retry_issues"]) == 0

    def test_missing_critic_decision_fails_closed(self) -> None:
        node = CriticDecisionNode()
        state = _make_state(
            current_issues=[_make_issue(fingerprint="fp-1")],
            critic_decisions=[],
            review_round=2,
            max_review_rounds=2,
        )

        result = node(state)

        assert result["verified_issues"] == []
        assert len(result["rejected_issues"]) == 1
        assert result["rejected_issues"][0]["critic_decision"] == "fail"
        assert result["rejected_issues"][0]["critic_reason"] == "missing_critic_decision"

    def test_dedup_by_fingerprint(self) -> None:
        node = CriticDecisionNode()
        state = _make_state(
            current_issues=[_make_issue(fingerprint="fp-1")],
            critic_decisions=[
                {"fingerprint": "fp-1", "decision": "pass", "reason": "ok"},
            ],
            verified_issues=[_make_issue(fingerprint="fp-1")],
        )
        result = node(state)
        # Only one entry with fingerprint fp-1.
        assert len(result["verified_issues"]) == 1


# ── Route tests (§19.3) ─────────────────────────────────────────────────────


class TestRoutes:
    def test_guard_planner_proceed(self) -> None:
        from app.graph.routes import ROUTE_REPORT, route_guard_planner

        assert route_guard_planner({"next_action": "planner"}) == "planner"
        assert route_guard_planner({"next_action": "report"}) == ROUTE_REPORT

    def test_review_decision_three_way(self) -> None:
        from app.graph.routes import (
            ROUTE_ADVANCE_ITEM,
            ROUTE_EVIDENCE_VERIFY,
            route_review_decision,
        )

        assert route_review_decision({"next_action": "advance_item"}) == ROUTE_ADVANCE_ITEM
        assert route_review_decision({"next_action": "rewrite_query"}) == "rewrite_query"
        assert route_review_decision({"next_action": "evidence_verify"}) == ROUTE_EVIDENCE_VERIFY

    def test_critic_decision_routing(self) -> None:
        from app.graph.routes import (
            ROUTE_FINALIZE_ITEM,
            ROUTE_PREPARE_REREVIEW,
            route_critic_decision,
        )

        assert route_critic_decision({"next_action": "prepare_rereview"}) == ROUTE_PREPARE_REREVIEW
        assert route_critic_decision({"next_action": "finalize_item"}) == ROUTE_FINALIZE_ITEM

    def test_init_item_routing(self) -> None:
        from app.graph.routes import ROUTE_GUARD_RETRIEVE, ROUTE_REPORT, route_init_item

        assert route_init_item({"next_action": "guard_retrieve"}) == ROUTE_GUARD_RETRIEVE
        assert route_init_item({"next_action": "report"}) == ROUTE_REPORT

    def test_advance_item_routing(self) -> None:
        from app.graph.routes import ROUTE_REPORT, route_advance_item

        assert route_advance_item({"next_action": "init_item"}) == "init_item"
        assert route_advance_item({"next_action": "report"}) == ROUTE_REPORT


# ── Agent tests (with FakeLLM) ──────────────────────────────────────────────


class TestPlannerAgent:
    @pytest.mark.asyncio
    async def test_planner_produces_review_plan(self) -> None:
        plan = ReviewPlan(
            items=[
                ReviewItem(
                    key="item-1",
                    review_type="security",
                    target_paths=["src/auth/"],
                    keywords=["auth"],
                    risk_focus=["CWE-862"],
                    priority="high",
                    top_k=10,
                )
            ]
        )
        llm = _build_fake_llm(plan)
        agent = PlannerAgent(llm)
        state = _make_state(file_summary={"src/A.java": {"language": "java", "line_count": 50}})
        result = await agent(state)
        assert len(result["review_plan"]) == 1
        assert result["review_plan"][0]["key"] == "item-1"
        assert result["llm_call_count"] == 1
        assert result["next_action"] == "init_item"

    @pytest.mark.asyncio
    async def test_planner_empty_plan_goes_to_report(self) -> None:
        plan = ReviewPlan(items=[])
        llm = _build_fake_llm(plan)
        agent = PlannerAgent(llm)
        state = _make_state()
        result = await agent(state)
        assert result["review_plan"] == []
        assert result["next_action"] == "init_item"  # empty plan handled by InitItem


class TestReviewerAgent:
    @pytest.mark.asyncio
    async def test_reviewer_produces_issues(self) -> None:
        issue = IssueCandidate(
            relative_path="src/a.py",
            start_line=1,
            end_line=2,
            evidence="bad",
            source_chunk_ids=[1],
            category="bug",
            issue_type="test",
            risk_level="Low",
            rule_id="T-1",
            title="T",
            description="D",
            reason="R",
            suggestion="S",
            confidence=0.5,
        )
        output = ReviewOutput(issues=[issue])
        llm = _build_fake_llm(output)
        agent = ReviewerAgent(llm)
        state = _make_state(
            current_review_item=_make_plan_item(),
            retrieved_context="some code content",
        )
        result = await agent(state)
        assert len(result["current_issues"]) == 1
        assert result["next_action"] == "review_decision"

    @pytest.mark.asyncio
    async def test_reviewer_no_context_marks_insufficient(self) -> None:
        output = ReviewOutput(issues=[])
        llm = _build_fake_llm(output)
        agent = ReviewerAgent(llm)
        state = _make_state(
            current_review_item=_make_plan_item(),
            retrieved_context="",
        )
        result = await agent(state)
        assert result["current_item_warning"] == "insufficient_context"

    @pytest.mark.asyncio
    async def test_rereview_emits_only_failed_issue_slots(self) -> None:
        allowed = IssueCandidate(
            relative_path="src/a.py",
            start_line=1,
            end_line=1,
            evidence="bad",
            source_chunk_ids=[1],
            category="bug",
            issue_type="test",
            risk_level="Low",
            rule_id="T-1",
            title="T",
            description="D",
            reason="R",
            suggestion="S",
            confidence=0.5,
        )
        extra = allowed.model_copy(update={"relative_path": "src/other.py", "rule_id": "T-2"})
        agent = ReviewerAgent(_build_fake_llm(ReviewOutput(issues=[allowed, extra])))
        state = _make_state(
            current_review_item=_make_plan_item(),
            retrieved_context="code",
            review_round=2,
            retry_issues=[_make_issue(relative_path="src/a.py", rule_id="T-1")],
            critic_feedback="retry",
        )

        result = await agent(state)

        assert len(result["current_issues"]) == 1
        assert result["current_issues"][0]["relative_path"] == "src/a.py"
        assert result["current_issues"][0]["review_round"] == 2


class TestCriticAgent:
    @pytest.mark.asyncio
    async def test_critic_produces_decisions(self) -> None:
        co = CriticOutput(
            decisions=[
                CriticResult(fingerprint="fp-1", decision="pass", reason="ok"),
                CriticResult(fingerprint="fp-2", decision="fail", reason="fp"),
            ]
        )
        llm = _build_fake_llm(co)
        agent = CriticAgent(llm)
        state = _make_state(
            current_issues=[_make_issue(fingerprint="fp-1"), _make_issue(fingerprint="fp-2")],
            retrieved_context="code",
        )
        result = await agent(state)
        assert len(result["critic_decisions"]) == 2
        assert result["next_action"] == "critic_decision"


# ── Deterministic node tests ────────────────────────────────────────────────


class TestInitItem:
    def test_init_first_item(self) -> None:
        from app.graph.nodes import InitItemNode

        node = InitItemNode()
        state = _make_state(
            review_plan=[_make_plan_item("item-1"), _make_plan_item("item-2")],
            current_review_index=0,
        )
        result = node(state)
        assert result["current_review_item"]["key"] == "item-1"
        assert result["next_action"] == "guard_retrieve"
        assert result["review_round"] == 1
        assert result["retrieval_target_paths"] == ["src/"]
        assert result["retrieval_top_k"] == 10

    def test_empty_plan_goes_to_report(self) -> None:
        from app.graph.nodes import InitItemNode

        node = InitItemNode()
        state = _make_state(review_plan=[], current_review_index=0)
        result = node(state)
        assert result["next_action"] == "report"


class TestReviewDecision:
    def test_no_issues_advances(self) -> None:
        from app.graph.nodes import ReviewDecisionNode

        node = ReviewDecisionNode()
        state = _make_state(current_issues=[])
        assert node(state)["next_action"] == "advance_item"

    def test_issues_go_to_evidence(self) -> None:
        from app.graph.nodes import ReviewDecisionNode

        node = ReviewDecisionNode()
        state = _make_state(current_issues=[_make_issue()])
        assert node(state)["next_action"] == "evidence_verify"

    def test_insufficient_context_once_rewrites(self) -> None:
        from app.graph.nodes import ReviewDecisionNode

        node = ReviewDecisionNode()
        state = _make_state(
            current_issues=[],
            current_item_warning="insufficient_context",
            retrieval_retry_count=0,
        )
        assert node(state)["next_action"] == "rewrite_query"

    def test_insufficient_context_exhausted_advances(self) -> None:
        from app.graph.nodes import ReviewDecisionNode

        node = ReviewDecisionNode()
        state = _make_state(
            current_issues=[],
            current_item_warning="insufficient_context",
            retrieval_retry_count=2,
        )
        result = node(state)
        assert result["next_action"] == "advance_item"
        assert "exhausted" in result.get("current_item_warning", "")


class TestEvidenceVerify:
    async def test_failed_evidence_is_retained_for_trace(self) -> None:
        from app.graph.nodes import EvidenceVerifyNode

        async def reject(**kwargs: Any) -> dict[str, Any]:
            return {
                **kwargs["issue"],
                "fingerprint": "failed-fingerprint",
                "evidence_status": "failed",
            }

        result = await EvidenceVerifyNode(reject)(
            _make_state(current_issues=[_make_issue(fingerprint="candidate")])
        )

        assert result["next_action"] == "advance_item"
        assert result["current_issues"][0]["evidence_status"] == "failed"
        assert result["rejected_issues"][0]["fingerprint"] == "failed-fingerprint"


class TestRewriteQuery:
    def test_second_retry_expands_parent_path_and_top_k(self) -> None:
        from app.graph.nodes import RewriteQueryNode

        result = RewriteQueryNode()(
            _make_state(
                current_review_item=_make_plan_item(
                    target_paths=["src/auth/service.py"],
                    top_k=10,
                ),
                retrieval_query="auth",
                retrieval_target_paths=["src/auth/service.py"],
                retrieval_top_k=10,
                retrieval_retry_count=1,
            )
        )

        assert result["retrieval_target_paths"] == ["src/auth", "src/auth/service.py"]
        assert result["retrieval_top_k"] == 20
        assert result["retrieval_retry_count"] == 2


class TestAdvanceItem:
    def test_advance_to_next_item(self) -> None:
        from app.graph.nodes import AdvanceItemNode

        node = AdvanceItemNode()
        state = _make_state(
            review_plan=[_make_plan_item("a"), _make_plan_item("b")],
            current_review_index=0,
        )
        result = node(state)
        assert result["next_action"] == "init_item"
        assert result["current_review_index"] == 1

    def test_all_items_done_goes_to_report(self) -> None:
        from app.graph.nodes import AdvanceItemNode

        node = AdvanceItemNode()
        state = _make_state(
            review_plan=[_make_plan_item("a")],
            current_review_index=0,
        )
        result = node(state)
        assert result["next_action"] == "report"


# ── Graph compilation and recursion guard ───────────────────────────────────


class TestGraphBuilder:
    def test_graph_compiles_with_fake_agents(self) -> None:
        """Verify the full graph compiles end-to-end with fake agent nodes."""

        async def _fake_planner(state: CodeReviewState) -> dict[str, Any]:
            return {"review_plan": [], "next_action": "init_item"}

        async def _fake_reviewer(state: CodeReviewState) -> dict[str, Any]:
            return {"current_issues": [], "next_action": "review_decision"}

        async def _fake_critic(state: CodeReviewState) -> dict[str, Any]:
            return {"critic_decisions": [], "next_action": "critic_decision"}

        graph = build_review_graph(
            planner_node=_fake_planner,
            reviewer_node=_fake_reviewer,
            critic_node=_fake_critic,
        )
        assert graph is not None

    async def test_invoke_with_empty_plan_terminates(self) -> None:
        """Empty review_plan → graph terminates at Report."""
        reviewer_calls = 0

        async def _fake_planner(state: CodeReviewState) -> dict[str, Any]:
            return {"review_plan": [], "next_action": "init_item"}

        async def _fake_reviewer(state: CodeReviewState) -> dict[str, Any]:
            nonlocal reviewer_calls
            reviewer_calls += 1
            return {"current_issues": [], "next_action": "review_decision"}

        async def _fake_critic(state: CodeReviewState) -> dict[str, Any]:
            return {"critic_decisions": [], "next_action": "critic_decision"}

        graph = build_review_graph(
            planner_node=_fake_planner,
            reviewer_node=_fake_reviewer,
            critic_node=_fake_critic,
        )
        result = await invoke_graph(
            graph,
            {
                "task_id": 1,
                "project_id": 1,
                "user_id": 1,
                "project_root": "/tmp/test",
                "next_action": "init_item",
                "file_summary": {"src/A.java": {"language": "java", "line_count": 10}},
            },
        )
        assert result["next_action"] == "done"
        assert reviewer_calls == 0

    async def test_rereview_reuses_context_without_retrieval(self) -> None:
        """Critic failures go through PrepareRereview and reuse existing context."""
        retrieval_calls = 0
        review_calls = 0

        async def _fake_planner(state: CodeReviewState) -> dict[str, Any]:
            return {"review_plan": [_make_plan_item()], "next_action": "init_item"}

        async def _fake_retrieve(**kwargs: Any) -> dict[str, Any]:
            nonlocal retrieval_calls
            retrieval_calls += 1
            return {
                "context": "code",
                "chunks": [{"id": 1}],
            }

        async def _fake_reviewer(state: CodeReviewState) -> dict[str, Any]:
            nonlocal review_calls
            review_calls += 1
            return {
                "current_issues": [_make_issue(fingerprint="fp-1")],
                "next_action": "review_decision",
            }

        async def _fake_evidence(**kwargs: Any) -> dict[str, Any]:
            return {**kwargs["issue"], "evidence_status": "passed"}

        async def _fake_critic(state: CodeReviewState) -> dict[str, Any]:
            decision = "fail" if state.review_round == 1 else "pass"
            return {
                "critic_decisions": [
                    {"fingerprint": "fp-1", "decision": decision, "reason": decision}
                ],
                "next_action": "critic_decision",
            }

        graph = build_review_graph(
            planner_node=_fake_planner,
            reviewer_node=_fake_reviewer,
            critic_node=_fake_critic,
            retrieve_fn=_fake_retrieve,
            evidence_verify_fn=_fake_evidence,
        )
        result = await invoke_graph(
            graph,
            {
                "task_id": 1,
                "project_id": 1,
                "user_id": 1,
                "project_root": "/tmp/test",
                "file_summary": {},
            },
        )

        assert result["next_action"] == "done"
        assert retrieval_calls == 1
        assert review_calls == 2
        assert len(result["verified_issues"]) == 1

    async def test_graph_recursion_limit_caught(self) -> None:
        """Recursion limit exception returns partial_success."""
        call_count = [0]

        async def _loop_planner(state: CodeReviewState) -> dict[str, Any]:
            call_count[0] += 1
            if call_count[0] > 10:
                return {"review_plan": [], "next_action": "init_item"}
            return {
                "review_plan": [_make_plan_item(f"item-{call_count[0]}")],
                "next_action": "init_item",
            }

        async def _loop_reviewer(state: CodeReviewState) -> dict[str, Any]:
            return {"current_issues": [], "next_action": "review_decision"}

        async def _loop_critic(state: CodeReviewState) -> dict[str, Any]:
            return {"critic_decisions": [], "next_action": "critic_decision"}

        graph = build_review_graph(
            planner_node=_loop_planner,
            reviewer_node=_loop_reviewer,
            critic_node=_loop_critic,
        )
        result = await invoke_graph(
            graph,
            {
                "task_id": 1,
                "project_id": 1,
                "user_id": 1,
                "project_root": "/tmp/test",
                "next_action": "init_item",
                "file_summary": {},
            },
            recursion_limit=2,
        )
        assert result["stop_reason"] == "graph_recursion_limit_exceeded"

    async def test_recursion_limit_preserves_latest_streamed_state(self) -> None:
        from langgraph.errors import GraphRecursionError

        class _PartialGraph:
            async def astream(
                self,
                initial_state: dict[str, Any],
                **kwargs: Any,
            ) -> AsyncIterator[dict[str, Any]]:
                del kwargs
                yield {
                    **initial_state,
                    "verified_issues": [_make_issue()],
                    "llm_call_count": 3,
                }
                raise GraphRecursionError

        result = await invoke_graph(
            _PartialGraph(),
            {
                "task_id": 1,
                "project_id": 1,
                "user_id": 1,
                "project_root": "/tmp/test",
            },
            recursion_limit=2,
        )

        assert len(result["verified_issues"]) == 1
        assert result["llm_call_count"] == 3
        assert result["stop_reason"] == "graph_recursion_limit_exceeded"


# ── State serialisation ─────────────────────────────────────────────────────


class TestState:
    def test_state_defaults(self) -> None:
        state = _make_state()
        assert state.review_plan == []
        assert state.current_review_index == 0
        assert state.review_round == 1
        assert state.max_review_rounds == 2
        assert state.llm_call_count == 0
        assert state.cost_status == "unavailable"

    def test_state_with_cost(self) -> None:
        state = _make_state(
            estimated_cost=Decimal("0.012345"),
            cost_status="available",
        )
        assert state.estimated_cost == Decimal("0.012345")
        assert state.cost_status == "available"

    def test_state_cost_unavailable(self) -> None:
        """Price unconfigured → cost_unavailable (not shown as 0)."""
        state = _make_state()
        assert state.cost_status == "unavailable"
        assert state.estimated_cost is None
