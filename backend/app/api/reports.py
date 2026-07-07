"""Report API endpoints per spec §16.

GET  /api/v1/reviews/{task_id}/report       — full report JSON
GET  /api/v1/reviews/{task_id}/issues       — issue list
GET  /api/v1/issues/{issue_id}              — single issue detail
PATCH /api/v1/issues/{issue_id}/feedback    — human feedback
GET  /api/v1/reviews/{task_id}/export?format=markdown  — export
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Security
from fastapi.responses import PlainTextResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_session
from app.core.exceptions import AppError
from app.core.security import AccessTokenService, authentication_error, get_token_service
from app.models.issue import ReviewIssue
from app.models.report import ReviewReport

router = APIRouter(tags=["reports"])
bearer_scheme = HTTPBearer(auto_error=False)
SessionDep = Annotated[AsyncSession, Depends(get_session)]
BearerDep = Annotated[
    HTTPAuthorizationCredentials | None,
    Security(bearer_scheme),
]


async def _require_user(
    credentials: BearerDep,
    token_service: Annotated[AccessTokenService, Depends(get_token_service)],
) -> int:
    """Extract and validate user ID from Bearer token."""
    if credentials is None:
        raise authentication_error()
    try:
        return token_service.subject(credentials.credentials)
    except Exception as exc:
        raise authentication_error() from exc


@router.get("/reviews/{task_id}/report")
async def get_report(
    task_id: int,
    session: SessionDep,
    user_id: Annotated[int, Depends(_require_user)],
) -> dict[str, Any]:
    """Return the full report for a review task (JSON)."""
    report = await session.scalar(
        select(ReviewReport).where(ReviewReport.task_id == task_id)
    )
    if report is None:
        raise AppError(
            code="REPORT_NOT_FOUND",
            message="Report not found for this task. The review may still be running.",
            status_code=404,
        )
    return {
        "task_id": report.task_id,
        "project_id": report.project_id,
        "summary": report.summary,
        "report_content": report.report_content,
        "severity_stats": report.severity_stats,
        "issue_type_stats": report.issue_type_stats,
        "coverage_summary": report.coverage_summary,
        "metrics_summary": report.metrics_summary,
        "degradation_summary": report.degradation_summary,
        "created_at": report.created_at.isoformat() if report.created_at else None,
    }


@router.get("/reviews/{task_id}/issues")
async def list_issues(
    task_id: int,
    session: SessionDep,
    user_id: Annotated[int, Depends(_require_user)],
) -> list[dict[str, Any]]:
    """List all issues for a review task."""
    rows = await session.scalars(select(ReviewIssue).where(ReviewIssue.task_id == task_id))
    return [
        {
            "id": issue.id,
            "task_id": issue.task_id,
            "fingerprint": issue.fingerprint,
            "title": issue.title,
            "category": issue.category,
            "issue_type": issue.issue_type,
            "risk_level": issue.risk_level,
            "rule_id": issue.rule_id,
            "cwe_id": issue.cwe_id,
            "relative_path": issue.relative_path,
            "start_line": issue.start_line,
            "end_line": issue.end_line,
            "evidence": issue.evidence,
            "description": issue.description,
            "reason": issue.reason,
            "suggestion": issue.suggestion,
            "fixed_example": issue.fixed_example,
            "confidence": issue.confidence,
            "evidence_status": issue.evidence_status,
            "critic_decision": issue.critic_decision,
            "critic_reason": issue.critic_reason,
            "needs_human_review": issue.needs_human_review,
            "review_round": issue.review_round,
            "status": issue.status,
            "created_at": issue.created_at.isoformat() if issue.created_at else None,
        }
        for issue in rows
    ]


@router.get("/issues/{issue_id}")
async def get_issue(
    issue_id: int,
    session: SessionDep,
    user_id: Annotated[int, Depends(_require_user)],
) -> dict[str, Any]:
    """Get a single issue with full detail."""
    issue = await session.get(ReviewIssue, issue_id)
    if issue is None:
        raise AppError(
            code="ISSUE_NOT_FOUND",
            message="Issue not found.",
            status_code=404,
        )
    return {
        "id": issue.id,
        "task_id": issue.task_id,
        "fingerprint": issue.fingerprint,
        "title": issue.title,
        "category": issue.category,
        "issue_type": issue.issue_type,
        "risk_level": issue.risk_level,
        "rule_id": issue.rule_id,
        "cwe_id": issue.cwe_id,
        "relative_path": issue.relative_path,
        "start_line": issue.start_line,
        "end_line": issue.end_line,
        "evidence": issue.evidence,
        "description": issue.description,
        "reason": issue.reason,
        "suggestion": issue.suggestion,
        "fixed_example": issue.fixed_example,
        "confidence": issue.confidence,
        "evidence_status": issue.evidence_status,
        "critic_decision": issue.critic_decision,
        "critic_reason": issue.critic_reason,
        "needs_human_review": issue.needs_human_review,
        "status": issue.status,
        "created_at": issue.created_at.isoformat() if issue.created_at else None,
    }


@router.patch("/issues/{issue_id}/feedback")
async def submit_feedback(
    issue_id: int,
    feedback: dict[str, Any],
    session: SessionDep,
    user_id: Annotated[int, Depends(_require_user)],
) -> dict[str, Any]:
    """Record human feedback on an issue (confirm / dismiss / adjust)."""
    issue = await session.get(ReviewIssue, issue_id)
    if issue is None:
        raise AppError(
            code="ISSUE_NOT_FOUND",
            message="Issue not found.",
            status_code=404,
        )
    new_status = feedback.get("status")
    if new_status in ("confirmed", "false_positive", "dismissed", "needs_review"):
        issue.status = new_status
        await session.commit()
    return {"id": issue.id, "status": issue.status}


@router.get("/reviews/{task_id}/export")
async def export_report(
    task_id: int,
    session: SessionDep,
    user_id: Annotated[int, Depends(_require_user)],
    format: str = Query("markdown"),
) -> PlainTextResponse:
    """Export the report in the requested format (markdown only for M11)."""
    report = await session.scalar(
        select(ReviewReport).where(ReviewReport.task_id == task_id)
    )
    if report is None:
        raise AppError(
            code="REPORT_NOT_FOUND",
            message="Report not found for this task.",
            status_code=404,
        )
    if format == "markdown":
        return PlainTextResponse(
            content=report.report_content,
            media_type="text/markdown; charset=utf-8",
        )
    raise AppError(
        code="UNSUPPORTED_FORMAT",
        message=f"Unsupported export format: {format}",
        status_code=400,
    )
