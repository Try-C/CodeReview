"""Unit tests for ReportService per spec §17.3."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.llm.client import FakeLLMClient
from app.services.report_service import (
    ReportData,
    ReportService,
    _fallback_summary,
)

# ── Helpers ─────────────────────────────────────────────────────────────────


def _make_issue(**overrides: object) -> dict[str, object]:
    d: dict[str, object] = {
        "relative_path": "src/Foo.java",
        "start_line": 10,
        "end_line": 12,
        "evidence": "bad code",
        "category": "security",
        "issue_type": "SQL Injection",
        "risk_level": "High",
        "rule_id": "T-001",
        "cwe_id": "CWE-89",
        "title": "Test issue",
        "description": "Test description",
        "reason": "Test reason",
        "suggestion": "Test suggestion",
        "confidence": 0.95,
        "fingerprint": "fp-001",
        "critic_decision": "pass",
        "critic_reason": "",
        "needs_human_review": False,
        "evidence_status": "passed",
        "review_round": 1,
    }
    d.update(overrides)
    return d


# ── ReportData tests ────────────────────────────────────────────────────────


class TestReportData:
    def test_defaults(self) -> None:
        rd = ReportData(task_id=1, project_id=1)
        assert rd.task_id == 1
        assert rd.severity_stats == {"high": 0, "medium": 0, "low": 0, "total": 0}
        assert rd.verified_issues == []
        assert rd.rejected_issues == []
        assert rd.cost_status == "unavailable"

    def test_to_dict(self) -> None:
        rd = ReportData(
            task_id=1,
            project_id=1,
            project_name="test",
            severity_stats={"high": 1, "medium": 0, "low": 0, "total": 1},
            estimated_cost=Decimal("0.000700"),
            cost_status="available",
        )
        d = rd.to_dict()
        assert d["task_id"] == 1
        assert d["project_name"] == "test"
        assert d["severity_stats"]["high"] == 1
        assert d["estimated_cost"] == "0.000700"
        assert d["cost_status"] == "available"


# ── ReportService.build tests ───────────────────────────────────────────────


class TestReportServiceBuild:
    def test_build_empty(self) -> None:
        svc = ReportService()
        report = svc.build(task_id=1, project_id=1)
        assert report.task_id == 1
        assert report.severity_stats == {"high": 0, "medium": 0, "low": 0, "total": 0}
        assert report.issue_type_stats == {}

    def test_build_with_issues(self) -> None:
        svc = ReportService()
        report = svc.build(
            task_id=1,
            project_id=1,
            verified_issues=[
                _make_issue(risk_level="High", category="security"),
                _make_issue(risk_level="Medium", category="bug"),
                _make_issue(risk_level="Low", category="performance"),
            ],
        )
        assert report.severity_stats == {"high": 1, "medium": 1, "low": 1, "total": 3}
        assert report.issue_type_stats == {"security": 1, "bug": 1, "performance": 1}

    def test_build_with_rejected(self) -> None:
        svc = ReportService()
        report = svc.build(
            task_id=1,
            project_id=1,
            verified_issues=[_make_issue()],
            rejected_issues=[_make_issue(risk_level="Low")],
        )
        # rejected issues also count in severity stats
        assert report.severity_stats["total"] == 2
        assert len(report.verified_issues) == 1
        assert len(report.rejected_issues) == 1

    def test_build_with_metrics(self) -> None:
        svc = ReportService()
        started = datetime(2026, 7, 6, 10, 0, 0, tzinfo=UTC)
        finished = datetime(2026, 7, 6, 10, 0, 5, tzinfo=UTC)
        report = svc.build(
            task_id=1,
            project_id=1,
            llm_call_count=3,
            input_tokens=1000,
            output_tokens=500,
            estimated_cost=Decimal("0.000700"),
            cost_status="available",
            started_at=started,
            finished_at=finished,
        )
        m = report.metrics_summary
        assert m["llm_call_count"] == 3
        assert m["input_tokens"] == 1000
        assert m["output_tokens"] == 500
        assert m["cost_status"] == "available"
        assert m["cost_display"] == "$0.000700"
        assert m["elapsed_seconds"] == 5.0

    def test_build_cost_unavailable(self) -> None:
        svc = ReportService()
        report = svc.build(task_id=1, project_id=1, cost_status="unavailable")
        assert report.metrics_summary["cost_display"] == "cost_unavailable"

    def test_build_cost_partial(self) -> None:
        svc = ReportService()
        report = svc.build(
            task_id=1,
            project_id=1,
            estimated_cost=Decimal("0.001000"),
            cost_status="partial",
        )
        assert "~" in str(report.metrics_summary["cost_display"])

    def test_build_with_stop_reason(self) -> None:
        svc = ReportService()
        report = svc.build(
            task_id=1, project_id=1, stop_reason="budget_guard_llm_call_limit_exceeded"
        )
        assert report.stop_reason == "budget_guard_llm_call_limit_exceeded"


# ── Summary / LLM tests ─────────────────────────────────────────────────────


class TestReportServiceSummary:
    @pytest.mark.asyncio
    async def test_fallback_summary_no_issues(self) -> None:
        svc = ReportService()
        report = svc.build(task_id=1, project_id=1)
        summary = await svc.generate_summary(report)
        assert summary is not None
        assert "No issues were identified" in summary

    @pytest.mark.asyncio
    async def test_fallback_summary_with_issues(self) -> None:
        svc = ReportService()
        report = svc.build(
            task_id=1,
            project_id=1,
            verified_issues=[_make_issue(), _make_issue(risk_level="Medium")],
        )
        summary = await svc.generate_summary(report)
        assert summary is not None
        assert "2 issue" in summary

    @pytest.mark.asyncio
    async def test_llm_summary_success(self) -> None:
        fake = FakeLLMClient(response_text="Custom LLM summary text.")
        svc = ReportService(llm=fake)
        report = svc.build(task_id=1, project_id=1)
        summary = await svc.generate_summary(report)
        assert summary == "Custom LLM summary text."

    @pytest.mark.asyncio
    async def test_llm_summary_falls_back_on_error(self) -> None:
        fake = FakeLLMClient(response_text="ok")
        svc = ReportService(llm=fake)

        class BadReport:
            pass  # triggers exception in _build_summary_prompt

        # Patch chat to simulate an LLM error → fallback to deterministic summary.
        async def bad_chat(*args: object, **kwargs: object) -> object:
            raise RuntimeError("simulated error")

        fake.chat = bad_chat  # type: ignore[assignment]
        report = svc.build(task_id=1, project_id=1)
        summary = await svc.generate_summary(report)
        assert summary is not None  # falls back
        assert "no" in summary.lower() or "0" in summary or "No issues" in summary


# ── Markdown rendering ──────────────────────────────────────────────────────


class TestMarkdownRendering:
    def test_empty_report(self) -> None:
        svc = ReportService()
        report = svc.build(task_id=1, project_id=1, project_name="Test")
        md = svc.render_markdown(report)
        assert "# Code Review Report" in md
        assert "Test" in md
        assert "## Severity" in md
        assert "## Metrics" in md

    def test_report_with_issues(self) -> None:
        svc = ReportService()
        report = svc.build(
            task_id=1,
            project_id=1,
            project_name="Demo",
            verified_issues=[_make_issue()],
        )
        md = svc.render_markdown(report, summary="A custom summary.")
        assert "A custom summary." in md
        assert "Test issue" in md
        assert "SQL Injection" in md
        assert "CWE-89" in md
        assert "bad code" in md

    def test_report_with_rejected(self) -> None:
        svc = ReportService()
        report = svc.build(
            task_id=1,
            project_id=1,
            rejected_issues=[_make_issue(title="Rejected issue", risk_level="Low")],
        )
        md = svc.render_markdown(report)
        assert "Rejected Issues" in md
        assert "Rejected issue" in md

    def test_report_with_degradation(self) -> None:
        svc = ReportService()
        report = svc.build(
            task_id=1,
            project_id=1,
            degradation_summary={"embedding": "keyword_only"},
        )
        md = svc.render_markdown(report)
        assert "## Degradation" in md
        assert "embedding" in md

    def test_report_with_coverage_section(self) -> None:
        svc = ReportService()
        report = svc.build(
            task_id=1,
            project_id=1,
            coverage_summary={"total_plan_items": 5, "verified_issues": 3, "rejected_issues": 1},
        )
        md = svc.render_markdown(report)
        assert "## Coverage" in md

    def test_report_with_stop_reason(self) -> None:
        svc = ReportService()
        report = svc.build(task_id=1, project_id=1, stop_reason="graph_recursion_limit_exceeded")
        md = svc.render_markdown(report)
        assert "graph_recursion_limit_exceeded" in md


# ── Fallback summary ────────────────────────────────────────────────────────


class TestFallbackSummary:
    def test_no_issues(self) -> None:
        report = ReportData(task_id=1, project_id=1)
        s = _fallback_summary(report)
        assert "No issues were identified" in s

    def test_with_issues(self) -> None:
        report = ReportData(
            task_id=1,
            project_id=1,
            severity_stats={"high": 2, "medium": 1, "low": 0, "total": 3},
        )
        s = _fallback_summary(report)
        assert "3 issue" in s
        assert "2 high" in s


# ── Edge cases ──────────────────────────────────────────────────────────────


class TestEdgeCases:
    def test_unknown_risk_level_gets_own_count(self) -> None:
        svc = ReportService()
        report = svc.build(
            task_id=1,
            project_id=1,
            verified_issues=[_make_issue(risk_level="Unknown")],
        )
        assert report.severity_stats["total"] == 1
        # "Unknown" gets its own Counter entry, not mapped to Low
        assert report.severity_stats["high"] == 0

    def test_empty_verified_and_rejected(self) -> None:
        svc = ReportService()
        report = svc.build(task_id=1, project_id=1)
        assert report.verified_issues == []
        assert report.rejected_issues == []
        assert report.severity_stats["total"] == 0


def test_reports_router_has_endpoints() -> None:
    from app.api.reports import router

    assert len(router.routes) >= 5  # report, issues, issue detail, feedback, export


class TestRequireUser:
    async def test_raises_without_credentials(self) -> None:
        from app.api.reports import _require_user
        from app.core.exceptions import AppError
        from app.core.security import get_token_service

        with pytest.raises(AppError) as exc:
            await _require_user(credentials=None, token_service=get_token_service())
        assert exc.value.code == "AUTHENTICATION_REQUIRED"

    async def test_raises_with_bad_token(self) -> None:
        from fastapi.security import HTTPAuthorizationCredentials

        from app.api.reports import _require_user
        from app.core.exceptions import AppError
        from app.core.security import get_token_service

        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="bad.token.here")
        with pytest.raises(AppError) as exc:
            await _require_user(credentials=creds, token_service=get_token_service())
        assert exc.value.code == "AUTHENTICATION_REQUIRED"
