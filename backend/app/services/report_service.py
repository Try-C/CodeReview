"""Deterministic report generation per spec §17.3.

System code handles counts, distributions, coverage, and markdown rendering.
LLM is only used for a natural-language summary; if it fails the report is
still complete.
"""

from __future__ import annotations

import logging
from collections import Counter
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from app.llm.client import FakeLLMClient, LLMClient

logger = logging.getLogger(__name__)


class ReportService:
    """Produce a deterministic review report from graph results.

    Constructor accepts an optional LLM client for summary generation.
    Pass a FakeLLMClient to skip LLM calls (tests / cost-unaware envs).
    """

    def __init__(self, llm: LLMClient | FakeLLMClient | None = None) -> None:
        self._llm = llm

    # ── Public API ────────────────────────────────────────────────────────

    def build(
        self,
        *,
        task_id: int,
        project_id: int,
        project_name: str = "",
        verified_issues: list[dict[str, Any]] | None = None,
        rejected_issues: list[dict[str, Any]] | None = None,
        coverage_summary: dict[str, Any] | None = None,
        degradation_summary: dict[str, Any] | None = None,
        review_plan: list[dict[str, Any]] | None = None,
        llm_call_count: int = 0,
        input_tokens: int = 0,
        output_tokens: int = 0,
        estimated_cost: Decimal | None = None,
        cost_status: str = "unavailable",
        stop_reason: str | None = None,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
    ) -> ReportData:
        """Assemble a complete report from graph outputs."""
        verified = verified_issues or []
        rejected = rejected_issues or []
        all_issues = verified + rejected
        cov = coverage_summary or {}

        severity_stats = self._build_severity_stats(all_issues)
        issue_type_stats = self._build_issue_type_stats(all_issues)
        metrics = self._build_metrics(
            llm_call_count,
            input_tokens,
            output_tokens,
            estimated_cost,
            cost_status,
            started_at,
            finished_at,
        )
        degradation = degradation_summary or {}

        return ReportData(
            task_id=task_id,
            project_id=project_id,
            project_name=project_name,
            severity_stats=severity_stats,
            issue_type_stats=issue_type_stats,
            coverage_summary=cov,
            metrics_summary=metrics,
            degradation_summary=degradation,
            verified_issues=verified,
            rejected_issues=rejected,
            review_plan=review_plan or [],
            llm_call_count=llm_call_count,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost=estimated_cost,
            cost_status=cost_status,
            stop_reason=stop_reason,
            started_at=started_at.isoformat() if started_at else None,
            finished_at=finished_at.isoformat() if finished_at else None,
        )

    async def generate_summary(
        self,
        report: ReportData,
    ) -> str | None:
        """Generate a natural-language summary via LLM.  Returns None on failure."""
        if self._llm is None:
            return _fallback_summary(report)
        try:
            messages = [
                {
                    "role": "system",
                    "content": (
                        "You are a code review reporter.  Write a concise summary "
                        "of the findings below.  Do not fabricate data — only "
                        "report what is present.  Keep the summary under 500 words."
                    ),
                },
                {
                    "role": "user",
                    "content": _build_summary_prompt(report),
                },
            ]
            result = await self._llm.chat(messages, max_tokens=600)
            return result.content.strip()
        except Exception as exc:
            logger.warning("report_summary_llm_failed %s", exc)
            return _fallback_summary(report)

    @staticmethod
    def render_markdown(report: ReportData, summary: str | None = None) -> str:
        """Render the full report as Markdown — §17.2."""
        return _render_markdown(report, summary)

    # ── Statistics helpers ────────────────────────────────────────────────

    @staticmethod
    def _build_severity_stats(
        issues: list[dict[str, Any]],
    ) -> dict[str, int]:
        counter = Counter(i.get("risk_level", "Low") for i in issues)
        return {
            "high": counter.get("High", 0),
            "medium": counter.get("Medium", 0),
            "low": counter.get("Low", 0),
            "total": len(issues),
        }

    @staticmethod
    def _build_issue_type_stats(
        issues: list[dict[str, Any]],
    ) -> dict[str, int]:
        counter = Counter(i.get("category", "unknown") for i in issues)
        return dict(counter)

    @staticmethod
    def _build_metrics(
        llm_call_count: int,
        input_tokens: int,
        output_tokens: int,
        estimated_cost: Decimal | None,
        cost_status: str,
        started_at: datetime | None,
        finished_at: datetime | None,
    ) -> dict[str, Any]:
        elapsed: float | None = None
        if started_at and finished_at:
            elapsed = (finished_at - started_at).total_seconds()

        cost_display: str
        if cost_status == "available" and estimated_cost is not None:
            cost_display = f"${estimated_cost:.6f}"
        elif cost_status == "partial":
            cost_display = f"~${estimated_cost:.6f}" if estimated_cost else "partial"
        else:
            cost_display = "cost_unavailable"

        return {
            "llm_call_count": llm_call_count,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "estimated_cost": str(estimated_cost) if estimated_cost is not None else None,
            "cost_status": cost_status,
            "cost_display": cost_display,
            "elapsed_seconds": round(elapsed, 1) if elapsed is not None else None,
        }


# ── Report data ─────────────────────────────────────────────────────────────


class ReportData:
    """Immutable-ish report value object."""

    __slots__ = (
        "cost_status",
        "coverage_summary",
        "degradation_summary",
        "estimated_cost",
        "finished_at",
        "input_tokens",
        "issue_type_stats",
        "llm_call_count",
        "metrics_summary",
        "output_tokens",
        "project_id",
        "project_name",
        "rejected_issues",
        "review_plan",
        "severity_stats",
        "started_at",
        "stop_reason",
        "task_id",
        "verified_issues",
    )

    def __init__(
        self,
        *,
        task_id: int,
        project_id: int,
        project_name: str = "",
        severity_stats: dict[str, int] | None = None,
        issue_type_stats: dict[str, int] | None = None,
        coverage_summary: dict[str, Any] | None = None,
        metrics_summary: dict[str, Any] | None = None,
        degradation_summary: dict[str, Any] | None = None,
        verified_issues: list[dict[str, Any]] | None = None,
        rejected_issues: list[dict[str, Any]] | None = None,
        review_plan: list[dict[str, Any]] | None = None,
        llm_call_count: int = 0,
        input_tokens: int = 0,
        output_tokens: int = 0,
        estimated_cost: Decimal | None = None,
        cost_status: str = "unavailable",
        stop_reason: str | None = None,
        started_at: str | None = None,
        finished_at: str | None = None,
    ) -> None:
        self.task_id = task_id
        self.project_id = project_id
        self.project_name = project_name
        self.severity_stats = severity_stats or {"high": 0, "medium": 0, "low": 0, "total": 0}
        self.issue_type_stats = issue_type_stats or {}
        self.coverage_summary = coverage_summary or {}
        self.metrics_summary = metrics_summary or {}
        self.degradation_summary = degradation_summary or {}
        self.verified_issues = verified_issues or []
        self.rejected_issues = rejected_issues or []
        self.review_plan = review_plan or []
        self.llm_call_count = llm_call_count
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.estimated_cost = estimated_cost
        self.cost_status = cost_status
        self.stop_reason = stop_reason
        self.started_at = started_at
        self.finished_at = finished_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "project_id": self.project_id,
            "project_name": self.project_name,
            "severity_stats": self.severity_stats,
            "issue_type_stats": self.issue_type_stats,
            "coverage_summary": self.coverage_summary,
            "metrics_summary": self.metrics_summary,
            "degradation_summary": self.degradation_summary,
            "verified_issues": self.verified_issues,
            "rejected_issues": self.rejected_issues,
            "review_plan": self.review_plan,
            "llm_call_count": self.llm_call_count,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "estimated_cost": str(self.estimated_cost) if self.estimated_cost else None,
            "cost_status": self.cost_status,
            "stop_reason": self.stop_reason,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


# ── Markdown rendering ──────────────────────────────────────────────────────


def _render_markdown(report: ReportData, summary: str | None = None) -> str:
    """Render the full report in Markdown."""
    sev = report.severity_stats
    lines = [
        f"# Code Review Report — {report.project_name or 'Unnamed Project'}",
        "",
        f"**Task ID:** {report.task_id}  ",
        f"**Generated:** {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}  ",
        f"**Cost:** {report.metrics_summary.get('cost_display', 'unavailable')}  ",
        f"**Duration:** {report.metrics_summary.get('elapsed_seconds', 'N/A')}s  ",
        "",
    ]

    if summary:
        lines.extend(["## Summary", "", summary, ""])

    if report.stop_reason:
        lines.extend(
            [
                "> ⚠️ **Stop reason:** " + report.stop_reason,
                "",
            ]
        )

    # Severity
    lines.extend(
        [
            "## Severity",
            "",
            "| Level  | Count |",
            "|--------|-------|",
            f"| 🔴 High   | {sev.get('high', 0)} |",
            f"| 🟡 Medium | {sev.get('medium', 0)} |",
            f"| 🟢 Low    | {sev.get('low', 0)} |",
            f"| **Total** | **{sev.get('total', 0)}** |",
            "",
        ]
    )

    # Type distribution
    if report.issue_type_stats:
        lines.extend(["## Issue Types", ""])
        for cat, count in sorted(report.issue_type_stats.items()):
            lines.append(f"- **{cat}**: {count}")
        lines.append("")

    # Coverage
    cov = report.coverage_summary
    if cov:
        lines.extend(
            [
                "## Coverage",
                "",
                f"- Plan items: {cov.get('total_plan_items', 'N/A')}",
                f"- Verified issues: {cov.get('verified_issues', 'N/A')}",
                f"- Rejected issues: {cov.get('rejected_issues', 'N/A')}",
                "",
            ]
        )

    # Degradation
    deg = report.degradation_summary
    if deg:
        lines.extend(["## Degradation", ""])
        for k, v in deg.items():
            lines.append(f"- **{k}**: {v}")
        lines.append("")

    # Issues — verified
    if report.verified_issues:
        lines.extend(
            [
                f"## Verified Issues ({len(report.verified_issues)})",
                "",
            ]
        )
        for idx, issue in enumerate(report.verified_issues, 1):
            lines.extend(_render_issue_markdown(idx, issue))

    # Issues — rejected
    if report.rejected_issues:
        lines.extend(
            [
                f"## Rejected Issues ({len(report.rejected_issues)})",
                "",
            ]
        )
        for idx, issue in enumerate(report.rejected_issues, 1):
            lines.extend(_render_issue_markdown(idx, issue))

    # Metrics
    m = report.metrics_summary
    lines.extend(
        [
            "## Metrics",
            "",
            f"- LLM calls: {m.get('llm_call_count', 0)}",
            f"- Input tokens: {m.get('input_tokens', 0):,}",
            f"- Output tokens: {m.get('output_tokens', 0):,}",
            f"- Estimated cost: {m.get('cost_display', 'unavailable')}",
            f"- Elapsed: {m.get('elapsed_seconds', 'N/A')}s",
            "",
        ]
    )

    return "\n".join(lines)


def _render_issue_markdown(idx: int, issue: dict[str, Any]) -> list[str]:
    """Render one issue as a Markdown block."""
    risk_icon = {"High": "🔴", "Medium": "🟡", "Low": "🟢"}.get(issue.get("risk_level", ""), "⚪")
    return [
        f"### {idx}. {risk_icon} {issue.get('title', 'Untitled')}",
        "",
        f"- **Category:** {issue.get('category', '?')}",
        f"- **Type:** {issue.get('issue_type', '?')}",
        f"- **Risk:** {issue.get('risk_level', '?')}",
        f"- **Rule:** {issue.get('rule_id', 'N/A')}",
        f"- **CWE:** {issue.get('cwe_id', 'N/A')}",
        f"- **File:** `{issue.get('relative_path', '?')}` "
        f"L{issue.get('start_line', 0)}-L{issue.get('end_line', 0)}",
        f"- **Confidence:** {issue.get('confidence', 0):.0%}",
        f"- **Critic:** {issue.get('critic_decision', 'pending')}",
        f"- **Human review:** {'Yes' if issue.get('needs_human_review') else 'No'}",
        "",
        "**Description:**",
        "",
        str(issue.get("description", "")),
        "",
        "**Evidence:**",
        "",
        "```",
        str(issue.get("evidence", "")),
        "```",
        "",
        "**Reason:**",
        "",
        str(issue.get("reason", "")),
        "",
        "**Suggestion:**",
        "",
        str(issue.get("suggestion", "")),
        "",
    ]


# ── Summary helpers ─────────────────────────────────────────────────────────


def _fallback_summary(report: ReportData) -> str:
    """Produce a deterministic summary without LLM."""
    sev = report.severity_stats
    total = sev.get("total", 0)
    high = sev.get("high", 0)
    if total == 0:
        return "No issues were identified during this review."
    return (
        f"This review found {total} issue(s): "
        f"{high} high, {sev.get('medium', 0)} medium, {sev.get('low', 0)} low."
    )


def _build_summary_prompt(report: ReportData) -> str:
    """Build a prompt with key stats for the LLM summary."""
    sev = report.severity_stats
    return (
        f"Project: {report.project_name}\n"
        f"Issues found: {sev.get('total', 0)} "
        f"(High: {sev.get('high', 0)}, "
        f"Medium: {sev.get('medium', 0)}, "
        f"Low: {sev.get('low', 0)})\n"
        f"Types: {report.issue_type_stats}\n"
        f"Stop reason: {report.stop_reason or 'completed'}\n"
        f"Elapsed: {report.metrics_summary.get('elapsed_seconds', 'N/A')}s\n"
        f"Cost: {report.metrics_summary.get('cost_display', 'unavailable')}"
    )
