"""Production orchestration for parsing, indexing, graph execution, and persistence."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents import CriticAgent, PlannerAgent, ReviewerAgent
from app.core.config import Settings
from app.graph import build_review_graph
from app.graph.builder import invoke_graph
from app.indexing.service import IndexingService
from app.languages.registry import LanguageAdapterRegistry
from app.llm.client import LLMProvider
from app.llm.structured import StructuredLLM
from app.models.issue import ReviewIssue, ReviewIssueChunk
from app.models.node_run import NodeRun
from app.models.project import Project, ProjectFile
from app.models.report import ReviewReport
from app.models.task import ReviewTask
from app.retrieval import ContextAssembler, HybridRetriever
from app.services.evidence_service import EvidenceService
from app.services.node_run_service import NodeRunService
from app.services.report_service import ReportService
from app.storage.local import LocalProjectStorage


class ReviewWorkflowService:
    """Run the complete non-HTTP review pipeline with injected providers."""

    def __init__(
        self,
        *,
        settings: Settings,
        sessions: async_sessionmaker[AsyncSession],
        storage: LocalProjectStorage,
        languages: LanguageAdapterRegistry,
        indexing: IndexingService,
        retriever: HybridRetriever,
        context_assembler: ContextAssembler,
        llm_provider: LLMProvider,
    ) -> None:
        self._settings = settings
        self._sessions = sessions
        self._storage = storage
        self._languages = languages
        self._indexing = indexing
        self._retriever = retriever
        self._context_assembler = context_assembler
        self._llm_provider = llm_provider
        self._evidence = EvidenceService()
        self._node_runs = NodeRunService(sessions)

    async def run(self, task_id: int) -> None:
        task, project, files = await self._load_inputs(task_id)
        await self._set_stage(task_id, "parsing")
        project_root = self._storage.project_path(project.storage_key)
        file_summary = await self._parse_and_index(project.id, project_root, files)
        parsed_count = sum(
            1 for v in file_summary.values() if v.get("parse_strategy") != "failed"
        )
        if parsed_count == 0:
            raise RuntimeError(
                f"All {len(file_summary)} files failed to parse — "
                "no source code available for review"
            )
        await self._set_stage(task_id, "planning")
        structured = StructuredLLM(self._llm_provider)
        graph = build_review_graph(
            planner_node=PlannerAgent(structured),
            reviewer_node=ReviewerAgent(structured),
            critic_node=CriticAgent(structured),
            retrieve_fn=self._retrieve,
            evidence_verify_fn=self._verify_evidence,
            node_run_writer=self._node_runs.record,
            cancel_check=self._cancel_requested,
        )
        await self._set_stage(task_id, "reviewing")
        result = await invoke_graph(
            graph,
            {
                "task_id": task.id,
                "project_id": project.id,
                "user_id": task.user_id,
                "project_root": str(project_root),
                "file_summary": file_summary,
                "max_review_rounds": self._settings.max_review_rounds,
                "cancel_requested": task.cancel_requested,
            },
        )
        await self._set_stage(task_id, "reporting")
        await self._persist_result(task, project, result)

    async def _set_stage(self, task_id: int, stage: str) -> None:
        """Update the task's current_stage so failures can be pinpointed."""
        async with self._sessions() as session:
            task = await session.get(ReviewTask, task_id)
            if task is not None:
                task.current_stage = stage
                await session.commit()

    async def _cancel_requested(self, task_id: int) -> bool:
        async with self._sessions() as session:
            value = await session.scalar(
                select(ReviewTask.cancel_requested).where(ReviewTask.id == task_id)
            )
            return bool(value)

    async def _load_inputs(
        self,
        task_id: int,
    ) -> tuple[ReviewTask, Project, list[ProjectFile]]:
        async with self._sessions() as session:
            task = await session.get(ReviewTask, task_id)
            if task is None:
                raise RuntimeError("Review task does not exist")
            project = await session.get(Project, task.project_id)
            if project is None:
                raise RuntimeError("Review task references a missing project")
            files = list(
                await session.scalars(
                    select(ProjectFile)
                    .where(
                        ProjectFile.project_id == project.id,
                        ProjectFile.scan_status == "included",
                    )
                    .order_by(ProjectFile.relative_path)
                )
            )
            session.expunge(task)
            session.expunge(project)
            for project_file in files:
                session.expunge(project_file)
            return task, project, files

    async def _parse_and_index(
        self,
        project_id: int,
        project_root: Path,
        files: list[ProjectFile],
    ) -> dict[str, Any]:
        summary: dict[str, Any] = {}
        for project_file in files:
            target = project_root.joinpath(*project_file.relative_path.split("/"))
            content = await asyncio.to_thread(target.read_text, encoding="utf-8")
            try:
                adapter = self._languages.resolve(project_file.relative_path, content)
                parsed = await asyncio.to_thread(
                    adapter.parse,
                    project_file.relative_path,
                    content,
                )
                await self._indexing.index_file(
                    project_id=project_id,
                    file_id=project_file.id,
                    file_hash=project_file.content_hash or "",
                    parse_result=parsed,
                )
            except Exception:
                await self._mark_parse_result(project_file.id, "failed", None, "PARSE_FAILED")
                summary[project_file.relative_path] = {
                    "language": project_file.language,
                    "line_count": project_file.line_count,
                    "priority": project_file.scan_priority,
                    "parse_strategy": "failed",
                    "parse_error": "PARSE_FAILED",
                }
                continue
            await self._mark_parse_result(
                project_file.id,
                "success",
                parsed.parse_strategy,
                "; ".join(parsed.errors) or None,
            )
            summary[project_file.relative_path] = {
                "language": project_file.language,
                "line_count": project_file.line_count,
                "priority": project_file.scan_priority,
                "parse_strategy": parsed.parse_strategy,
            }
        return summary

    async def _mark_parse_result(
        self,
        file_id: int,
        status: str,
        strategy: str | None,
        error: str | None,
    ) -> None:
        async with self._sessions() as session:
            project_file = await session.get(ProjectFile, file_id)
            if project_file is None:
                raise RuntimeError("Project file disappeared during parsing")
            project_file.parse_status = status
            project_file.parse_strategy = strategy
            project_file.parse_error = error
            await session.commit()

    async def _retrieve(self, **kwargs: Any) -> dict[str, Any]:
        target_paths = tuple(str(path) for path in kwargs.pop("target_paths", ()))
        top_k = min(int(kwargs.pop("top_k", self._settings.top_k)), self._settings.max_top_k)
        result = await self._retriever.retrieve(
            **kwargs,
            target_paths=target_paths,
            top_k=top_k,
        )
        scored = list(result.chunks)
        assembled = await self._context_assembler.assemble(scored)
        return {
            "context": "\n\n".join(item.format_for_llm() for item in assembled),
            "chunks": [
                {
                    "id": item.chunk_id,
                    "relative_path": item.relative_path,
                    "start_line": item.start_line,
                    "end_line": item.end_line,
                }
                for item in assembled
            ],
            "degradation": list(result.degradation),
        }

    async def _verify_evidence(self, **kwargs: Any) -> dict[str, Any]:
        async with self._sessions() as session:
            return await self._evidence.verify_one(**kwargs, session=session)

    async def _persist_result(
        self,
        task_snapshot: ReviewTask,
        project: Project,
        result: dict[str, Any],
    ) -> None:
        metrics = await self._aggregate_usage(task_snapshot.id)
        report_service = ReportService()
        finished_at = datetime.now(UTC)
        report_data = report_service.build(
            task_id=task_snapshot.id,
            project_id=project.id,
            project_name=project.project_name,
            verified_issues=result.get("verified_issues", []),
            rejected_issues=result.get("rejected_issues", []),
            coverage_summary=result.get("coverage_summary", {}),
            degradation_summary={
                "stop_reason": result.get("stop_reason"),
                "current_item_warning": result.get("current_item_warning"),
            },
            review_plan=result.get("review_plan", []),
            llm_call_count=metrics["llm_call_count"],
            input_tokens=metrics["input_tokens"],
            output_tokens=metrics["output_tokens"],
            estimated_cost=metrics["estimated_cost"],
            cost_status=metrics["cost_status"],
            stop_reason=result.get("stop_reason"),
            started_at=task_snapshot.started_at,
            finished_at=finished_at,
        )
        summary = await report_service.generate_summary(report_data)
        markdown = report_service.render_markdown(report_data, summary)

        async with self._sessions() as session:
            task = await session.get(ReviewTask, task_snapshot.id)
            if task is None:
                raise RuntimeError("Review task disappeared before result persistence")
            await self._replace_issues(
                session,
                task_id=task.id,
                project_id=project.id,
                issues=result.get("verified_issues", []) + result.get("rejected_issues", []),
            )
            report = await session.scalar(
                select(ReviewReport).where(ReviewReport.task_id == task.id)
            )
            if report is None:
                report = ReviewReport(
                    task_id=task.id,
                    project_id=project.id,
                    report_content=markdown,
                )
                session.add(report)
            report.summary = summary
            report.report_content = markdown
            report.severity_stats = report_data.severity_stats
            report.issue_type_stats = report_data.issue_type_stats
            report.coverage_summary = report_data.coverage_summary
            report.metrics_summary = report_data.metrics_summary
            report.degradation_summary = report_data.degradation_summary

            task.llm_call_count = metrics["llm_call_count"]
            task.input_tokens = metrics["input_tokens"]
            task.output_tokens = metrics["output_tokens"]
            task.estimated_cost = metrics["estimated_cost"]
            task.cost_status = metrics["cost_status"]
            task.pricing_summary = metrics["pricing_summary"]
            task.fallback_reason = result.get("stop_reason")
            await session.commit()

    async def _replace_issues(
        self,
        session: AsyncSession,
        *,
        task_id: int,
        project_id: int,
        issues: list[dict[str, Any]],
    ) -> None:
        issue_ids = select(ReviewIssue.id).where(ReviewIssue.task_id == task_id)
        await session.execute(
            delete(ReviewIssueChunk).where(ReviewIssueChunk.issue_id.in_(issue_ids))
        )
        await session.execute(delete(ReviewIssue).where(ReviewIssue.task_id == task_id))
        await session.flush()
        # Deduplicate by fingerprint — Critic re-review may produce duplicate entries
        seen: set[str] = set()
        for issue in issues:
            fp = str(issue.get("fingerprint", ""))
            if fp in seen:
                continue
            seen.add(fp)
            row = ReviewIssue(
                task_id=task_id,
                project_id=project_id,
                fingerprint=str(issue["fingerprint"]),
                title=str(issue["title"]),
                category=str(issue["category"]),
                issue_type=str(issue["issue_type"]),
                risk_level=str(issue["risk_level"]),
                rule_id=issue.get("rule_id"),
                cwe_id=issue.get("cwe_id"),
                relative_path=str(issue["relative_path"]),
                start_line=int(issue["start_line"]),
                end_line=int(issue["end_line"]),
                evidence=str(issue["evidence"]),
                description=str(issue["description"]),
                reason=str(issue["reason"]),
                suggestion=str(issue["suggestion"]),
                fixed_example=issue.get("fixed_example"),
                confidence=float(issue["confidence"]),
                evidence_status=str(issue.get("evidence_status", "passed")),
                critic_decision=issue.get("critic_decision"),
                critic_reason=issue.get("critic_reason"),
                needs_human_review=bool(issue.get("needs_human_review", False)),
                review_round=int(issue.get("review_round", 1)),
                status="open",
            )
            session.add(row)
            await session.flush()
            for chunk_id in set(issue.get("source_chunk_ids", [])):
                session.add(ReviewIssueChunk(issue_id=row.id, chunk_id=int(chunk_id)))

    async def _aggregate_usage(self, task_id: int) -> dict[str, Any]:
        async with self._sessions() as session:
            rows = list(
                await session.scalars(
                    select(NodeRun).where(
                        NodeRun.task_id == task_id,
                        NodeRun.status == "success",
                        NodeRun.usage_type.in_(("llm", "embedding")),
                    )
                )
            )
        llm_rows = [row for row in rows if row.usage_type == "llm"]
        llm_call_count = sum(
            int((row.output_summary or {}).get("model_call_count", 1)) for row in llm_rows
        )
        priced = [row for row in rows if row.cost_status == "available"]
        estimated_cost = (
            sum((row.estimated_cost or Decimal("0") for row in priced), Decimal("0"))
            if priced
            else None
        )
        if not rows or not priced:
            cost_status = "unavailable"
        elif len(priced) == len(rows):
            cost_status = "available"
        else:
            cost_status = "partial"

        pricing_groups: dict[str, dict[str, Any]] = defaultdict(
            lambda: {"calls": 0, "input_tokens": 0, "output_tokens": 0}
        )
        for row in rows:
            key = "/".join(
                (
                    row.provider or "unknown",
                    row.model_name or "unknown",
                    row.pricing_version or "unconfigured",
                )
            )
            pricing_groups[key]["calls"] += int(
                (row.output_summary or {}).get("model_call_count", 1)
            )
            pricing_groups[key]["input_tokens"] += row.input_tokens
            pricing_groups[key]["output_tokens"] += row.output_tokens

        return {
            "llm_call_count": llm_call_count,
            "input_tokens": sum(row.input_tokens for row in rows),
            "output_tokens": sum(row.output_tokens for row in llm_rows),
            "estimated_cost": estimated_cost,
            "cost_status": cost_status,
            "pricing_summary": dict(pricing_groups),
        }
