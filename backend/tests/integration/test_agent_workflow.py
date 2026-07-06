"""Production-style Agent workflow coverage with only fake model providers."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import Settings
from app.core.database import Base
from app.indexing import IndexingService
from app.indexing.service import IndexBuildResult
from app.languages import create_default_registry
from app.languages.schemas import ParseResult
from app.llm.usage import LLMCallResult, PricingSnapshot
from app.models import NodeRun, Project, ProjectFile, ReviewIssue, ReviewReport, ReviewTask, User
from app.retrieval import ContextAssembler, HybridRetriever
from app.services.review_workflow_service import ReviewWorkflowService
from app.storage.local import LocalProjectStorage


class FakeEmbeddingProvider:
    model = "text-embedding-v4"
    dimension = 1024

    async def embed(
        self,
        texts: Sequence[str],
        *,
        text_type: Literal["document", "query"],
    ) -> list[list[float]]:
        del text_type
        return [[1.0] * self.dimension for _ in texts]


class WorkflowLLMProvider:
    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMCallResult:
        del temperature, max_tokens
        system = messages[0]["content"]
        if "Planner agent" in system:
            content = json.dumps(
                {
                    "items": [
                        {
                            "key": "unsafe-eval",
                            "review_type": "security",
                            "target_paths": ["src/"],
                            "keywords": ["eval"],
                            "risk_focus": ["CWE-95"],
                            "priority": "high",
                            "top_k": 10,
                        }
                    ]
                }
            )
        elif "Review agent" in system:
            content = json.dumps(
                {
                    "issues": [
                        {
                            "relative_path": "src/example.py",
                            "start_line": 2,
                            "end_line": 2,
                            "evidence": "    return eval(user_input)",
                            "source_chunk_ids": [1],
                            "category": "security",
                            "issue_type": "Code Injection",
                            "risk_level": "High",
                            "rule_id": "PY-EVAL-001",
                            "cwe_id": "CWE-95",
                            "title": "Untrusted input reaches eval",
                            "description": "Input is executed as Python code.",
                            "reason": "eval executes attacker-controlled expressions.",
                            "suggestion": "Replace eval with an explicit parser.",
                            "confidence": 0.99,
                        }
                    ]
                }
            )
        else:
            match = re.search(r'"fingerprint":\s*"([0-9a-f]{64})"', messages[-1]["content"])
            assert match is not None
            content = json.dumps(
                {
                    "decisions": [
                        {
                            "fingerprint": match.group(1),
                            "decision": "pass",
                            "adjusted_risk_level": None,
                            "reason": "Evidence demonstrates executable input.",
                        }
                    ]
                }
            )
        return LLMCallResult(
            content=content,
            provider="fake",
            model="fake-review",
            input_tokens=10,
            output_tokens=5,
            cost_status="available",
            estimated_cost=Decimal("0.000001"),
            latency_ms=1,
            pricing=PricingSnapshot(
                model="fake-review",
                input_price_per_million=Decimal("0.10"),
                output_price_per_million=Decimal("0.20"),
                version="test-v1",
            ),
        )


class ExplodingIndexingService(IndexingService):
    async def index_file(
        self,
        *,
        project_id: int,
        file_id: int,
        file_hash: str,
        parse_result: ParseResult,
    ) -> IndexBuildResult:
        del project_id, file_id, file_hash, parse_result
        raise RuntimeError("index store unavailable")


async def test_workflow_persists_idempotent_trace_issue_and_report(tmp_path: Path) -> None:
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{(tmp_path / 'workflow.sqlite3').as_posix()}",
        poolclass=NullPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    settings = Settings(_env_file=None, app_env="test", upload_root=tmp_path / "uploads")
    storage = LocalProjectStorage(settings.upload_root)
    storage_key = "a" * 32
    project_root = settings.upload_root / storage_key
    (project_root / "src").mkdir(parents=True)
    source = "def unsafe(user_input):\n    return eval(user_input)\n"
    (project_root / "src" / "example.py").write_text(source, encoding="utf-8")
    task_id = await _create_task(sessions, storage_key, source)
    embeddings = FakeEmbeddingProvider()
    workflow = ReviewWorkflowService(
        settings=settings,
        sessions=sessions,
        storage=storage,
        languages=create_default_registry(settings),
        indexing=IndexingService(sessions, embeddings),
        retriever=HybridRetriever(sessions, embeddings),
        context_assembler=ContextAssembler(sessions),
        llm_provider=WorkflowLLMProvider(),
    )

    await workflow.run(task_id)
    first_node_count = await _count_rows(sessions, NodeRun)
    await workflow.run(task_id)

    async with sessions() as session:
        task = await session.get(ReviewTask, task_id)
        issues = list(await session.scalars(select(ReviewIssue)))
        report = await session.scalar(select(ReviewReport))
        assert task is not None
        assert task.llm_call_count == 3
        assert task.input_tokens == 30
        assert task.output_tokens == 15
        assert task.cost_status == "available"
        assert len(issues) == 1
        assert issues[0].critic_decision == "pass"
        assert report is not None
        assert "Untrusted input reaches eval" in report.report_content
    assert await _count_rows(sessions, NodeRun) == first_node_count
    await engine.dispose()


async def test_parse_index_failure_marks_file_failed_and_continues(tmp_path: Path) -> None:
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{(tmp_path / 'workflow-parse-failure.sqlite3').as_posix()}",
        poolclass=NullPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    settings = Settings(_env_file=None, app_env="test", upload_root=tmp_path / "uploads")
    storage = LocalProjectStorage(settings.upload_root)
    storage_key = "b" * 32
    project_root = settings.upload_root / storage_key
    (project_root / "src").mkdir(parents=True)
    source = "def ok():\n    return True\n"
    (project_root / "src" / "example.py").write_text(source, encoding="utf-8")
    task_id = await _create_task(sessions, storage_key, source)
    embeddings = FakeEmbeddingProvider()
    workflow = ReviewWorkflowService(
        settings=settings,
        sessions=sessions,
        storage=storage,
        languages=create_default_registry(settings),
        indexing=ExplodingIndexingService(sessions, embeddings),
        retriever=HybridRetriever(sessions, embeddings),
        context_assembler=ContextAssembler(sessions),
        llm_provider=WorkflowLLMProvider(),
    )
    _, project, files = await workflow._load_inputs(task_id)

    summary = await workflow._parse_and_index(project.id, project_root, files)

    assert summary == {
        "src/example.py": {
            "language": "python",
            "line_count": 2,
            "priority": "high",
            "parse_strategy": "failed",
            "parse_error": "PARSE_FAILED",
        }
    }
    async with sessions() as session:
        project_file = await session.scalar(select(ProjectFile))
        assert project_file is not None
        assert project_file.parse_status == "failed"
        assert project_file.parse_error == "PARSE_FAILED"
    await engine.dispose()


async def _create_task(
    sessions: async_sessionmaker[AsyncSession],
    storage_key: str,
    source: str,
) -> int:
    async with sessions.begin() as session:
        user = User(username="workflow-user", password_hash="hash")
        session.add(user)
        await session.flush()
        project = Project(
            user_id=user.id,
            project_name="workflow-project",
            storage_key=storage_key,
            status="scanned",
        )
        session.add(project)
        await session.flush()
        session.add(
            ProjectFile(
                project_id=project.id,
                relative_path="src/example.py",
                content_hash="f" * 64,
                language="python",
                size=len(source.encode("utf-8")),
                line_count=2,
                scan_status="included",
                scan_priority="high",
            )
        )
        task = ReviewTask(
            user_id=user.id,
            project_id=project.id,
            idempotency_key="workflow-task",
            status="running",
        )
        session.add(task)
        await session.flush()
        return task.id


async def _count_rows(
    sessions: async_sessionmaker[AsyncSession],
    model: type[Base],
) -> int:
    async with sessions() as session:
        count = await session.scalar(select(func.count()).select_from(model))
        return int(count or 0)
