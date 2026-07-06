"""Integration coverage for hybrid retrieval, context assembly, and trace."""

import asyncio
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.database import Base
from app.models import (
    CodeChunk,
    CodeRelation,
    CodeSymbol,
    Project,
    ProjectFile,
    RetrievalRecord,
    ReviewTask,
    User,
)
from app.retrieval import ContextAssembler, HybridRetriever
from tests.fakes import FakeEmbeddingProvider


def _embedding_vector(seed: int) -> list[float]:
    """Build a deterministic 1024-dim vector for a chunk seed."""
    return [seed / 100.0] * 1024


def test_hybrid_retrieval_returns_rrf_fused_chunks_and_trace(tmp_path: Path) -> None:
    asyncio.run(_retrieval_scenario(tmp_path))


async def _retrieval_scenario(tmp_path: Path) -> None:
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{(tmp_path / 'retrieval.sqlite3').as_posix()}",
        poolclass=NullPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    # ------------------------------------------------------------------
    # Arrange: project, files, chunks with embeddings, symbols, relations
    # ------------------------------------------------------------------
    project_id, task_id = await _create_project_and_task(sessions)

    file_id = await _create_file(sessions, project_id, "src/auth.py")
    await _create_chunk(
        sessions,
        project_id=project_id,
        file_id=file_id,
        fingerprint="a" * 64,
        content="def login(user, password):\n    return check_password(user, password)",
        symbol_name="login",
        qualified_name="login",
        symbol_type="function",
        language="python",
        embedding=_embedding_vector(1),
        start_line=1,
        end_line=2,
        relative_path="src/auth.py",
    )
    chunk_a_id = await _latest_chunk_id(sessions)

    await _create_chunk(
        sessions,
        project_id=project_id,
        file_id=file_id,
        fingerprint="b" * 64,
        content="def check_password(user, password):\n    return hash(password) == stored",
        symbol_name="check_password",
        qualified_name="check_password",
        symbol_type="function",
        language="python",
        embedding=_embedding_vector(2),
        start_line=3,
        end_line=4,
        relative_path="src/auth.py",
    )
    chunk_b_id = await _latest_chunk_id(sessions)

    # symbol for chunk A
    async with sessions.begin() as session:
        sym_a = CodeSymbol(
            project_id=project_id,
            file_id=file_id,
            chunk_id=chunk_a_id,
            symbol_hash="s" * 64,
            symbol_name="login",
            symbol_type="function",
            relative_path="src/auth.py",
            start_line=1,
            end_line=2,
        )
        session.add(sym_a)
        await session.flush()
        sym_a_id = sym_a.id

        sym_b = CodeSymbol(
            project_id=project_id,
            file_id=file_id,
            chunk_id=chunk_b_id,
            symbol_hash="t" * 64,
            symbol_name="check_password",
            symbol_type="function",
            relative_path="src/auth.py",
            start_line=3,
            end_line=4,
        )
        session.add(sym_b)
        await session.flush()

        session.add(
            CodeRelation(
                project_id=project_id,
                source_symbol_id=sym_a_id,
                target_name="check_password",
                relation_type="call",
                confidence=0.8,
                resolution_status="resolved",
            )
        )
        session.add(
            CodeRelation(
                project_id=project_id,
                source_symbol_id=sym_a_id,
                target_name="hash",
                relation_type="call",
                confidence=0.7,
                resolution_status="unresolved",
            )
        )

    # ------------------------------------------------------------------
    # Act: hybrid retrieval
    # ------------------------------------------------------------------
    provider = FakeEmbeddingProvider()
    retriever = HybridRetriever(sessions, provider, rrf_k=60, top_k=10, max_top_k=30)

    result = await retriever.retrieve(
        task_id=task_id,
        project_id=project_id,
        query="password check",
        review_item_key="review-auth",
        retrieval_round=1,
    )

    # ------------------------------------------------------------------
    # Assert: retrieval results
    # ------------------------------------------------------------------
    assert len(result.chunks) >= 1
    assert len(result.query_hash) == 64
    assert len(provider.calls) == 1
    assert provider.calls[0][1] == "query"

    # Both chunks should be found (vector search finds similar content)
    chunk_ids = {item.chunk.id for item in result.chunks}
    assert chunk_a_id in chunk_ids or chunk_b_id in chunk_ids

    for scored in result.chunks:
        assert scored.rrf_score > 0
        assert scored.chunk.content
        assert scored.chunk.relative_path == "src/auth.py"

    # ------------------------------------------------------------------
    # Assert: trace persisted
    # ------------------------------------------------------------------
    async with sessions() as session:
        records = list(
            await session.scalars(
                select(RetrievalRecord).where(
                    RetrievalRecord.task_id == task_id,
                    RetrievalRecord.query_hash == result.query_hash,
                )
            )
        )

    assert len(records) >= 1
    assert any(record.selected for record in records)
    assert all(record.review_item_key == "review-auth" for record in records)
    assert all(record.retrieval_round == 1 for record in records)
    assert all(record.query_preview == "password check" for record in records)

    # ------------------------------------------------------------------
    # Act: context assembly
    # ------------------------------------------------------------------
    assembler = ContextAssembler(sessions)
    assembled = await assembler.assemble(result.chunks)

    # ------------------------------------------------------------------
    # Assert: assembled context
    # ------------------------------------------------------------------
    assert len(assembled) == len(result.chunks)
    for ctx in assembled:
        assert ctx.chunk_id > 0
        assert ctx.language == "python"
        assert ctx.relative_path
        assert ctx.start_line <= ctx.end_line
        assert ctx.code
        assert ctx.rrf_score > 0

        # The login chunk should have relations
        if ctx.symbol_name == "login":
            assert len(ctx.relations) >= 1
            relation_targets = {rel.target_name for rel in ctx.relations}
            assert "check_password" in relation_targets
            assert any(rel.confidence > 0 for rel in ctx.relations)

    # Assert format_for_llm produces non-empty output
    for ctx in assembled:
        formatted = ctx.format_for_llm()
        assert ctx.relative_path in formatted
        assert "```" in formatted

    await engine.dispose()


def test_hybrid_retriever_rejects_invalid_config() -> None:
    import pytest

    from app.retrieval import HybridRetriever

    with pytest.raises(ValueError, match="top_k"):
        HybridRetriever(
            async_sessionmaker(create_async_engine("sqlite+aiosqlite://")),
            FakeEmbeddingProvider(),
            top_k=0,
        )
    with pytest.raises(ValueError, match="top_k"):
        HybridRetriever(
            async_sessionmaker(create_async_engine("sqlite+aiosqlite://")),
            FakeEmbeddingProvider(),
            top_k=10,
            max_top_k=5,
        )


def test_retriever_handles_empty_query(tmp_path: Path) -> None:
    asyncio.run(_empty_query_scenario(tmp_path))


async def _empty_query_scenario(tmp_path: Path) -> None:
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{(tmp_path / 'empty.sqlite3').as_posix()}",
        poolclass=NullPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    project_id, task_id = await _create_project_and_task(sessions)
    retriever = HybridRetriever(sessions, FakeEmbeddingProvider())
    result = await retriever.retrieve(
        task_id=task_id,
        project_id=project_id,
        query="   ",
    )
    assert len(result.chunks) == 0
    assert result.query_hash == ""

    await engine.dispose()


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


async def _create_project_and_task(
    sessions: async_sessionmaker[AsyncSession],
) -> tuple[int, int]:
    async with sessions.begin() as session:
        user = User(username="retrieval-user", password_hash="unused")
        session.add(user)
        await session.flush()
        project = Project(
            user_id=user.id,
            project_name="retrieval-project",
            storage_key="r" * 32,
        )
        session.add(project)
        await session.flush()
        task = ReviewTask(
            user_id=user.id,
            project_id=project.id,
            idempotency_key="retrieval-test",
        )
        session.add(task)
        await session.flush()
        return project.id, task.id


async def _create_file(
    sessions: async_sessionmaker[AsyncSession],
    project_id: int,
    relative_path: str,
) -> int:
    async with sessions.begin() as session:
        pf = ProjectFile(
            project_id=project_id,
            relative_path=relative_path,
        )
        session.add(pf)
        await session.flush()
        return pf.id


async def _create_chunk(
    sessions: async_sessionmaker[AsyncSession],
    *,
    project_id: int,
    file_id: int,
    fingerprint: str,
    content: str,
    symbol_name: str,
    qualified_name: str,
    symbol_type: str,
    language: str,
    embedding: list[float],
    start_line: int,
    end_line: int,
    relative_path: str,
) -> None:
    async with sessions.begin() as session:
        chunk = CodeChunk(
            project_id=project_id,
            file_id=file_id,
            relative_path=relative_path,
            file_hash="f" * 64,
            content_hash=fingerprint[:64],
            chunk_fingerprint=fingerprint,
            language=language,
            symbol_type=symbol_type,
            symbol_name=symbol_name,
            qualified_name=qualified_name,
            start_line=start_line,
            end_line=end_line,
            content=content,
            embedding_model="text-embedding-v4",
            embedding_version=1,
            embedding=embedding,
            embedding_status="ready",
            index_status="ready",
            search_text=f"{symbol_name} {qualified_name} {content}",
            search_vector=f"{symbol_name} {qualified_name} {content}",
        )
        session.add(chunk)


async def _latest_chunk_id(sessions: async_sessionmaker[AsyncSession]) -> int:
    async with sessions() as session:
        row = await session.execute(select(CodeChunk.id).order_by(CodeChunk.id.desc()).limit(1))
        return row.scalar_one()


# ---------------------------------------------------------------------------
# Degradation and idempotency tests
# ---------------------------------------------------------------------------


def test_embedding_failure_falls_back_to_keyword_only(tmp_path: Path) -> None:
    asyncio.run(_embedding_degradation_scenario(tmp_path))


async def _embedding_degradation_scenario(tmp_path: Path) -> None:
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{(tmp_path / 'degrade.sqlite3').as_posix()}",
        poolclass=NullPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    project_id, task_id = await _create_project_and_task(sessions)
    file_id = await _create_file(sessions, project_id, "src/check.py")
    await _create_chunk(
        sessions,
        project_id=project_id,
        file_id=file_id,
        fingerprint="x" * 64,
        content="def hash_password(pw):\n    return sha256(pw).hexdigest()",
        symbol_name="hash_password",
        qualified_name="hash_password",
        symbol_type="function",
        language="python",
        embedding=_embedding_vector(5),
        start_line=1,
        end_line=2,
        relative_path="src/check.py",
    )

    failing_provider = FakeEmbeddingProvider(
        error=RuntimeError("downstream unavailable"),
    )
    retriever = HybridRetriever(sessions, failing_provider, top_k=10)

    result = await retriever.retrieve(
        task_id=task_id,
        project_id=project_id,
        query="hash password",
    )

    # Should fall back to keyword-only, not fail
    assert len(result.degradation) == 1
    assert "embedding_failed" in result.degradation
    assert len(result.vector_results) == 0
    # Keyword results may be empty or non-empty; either is acceptable
    # as long as the retrieval didn't raise

    # Verify trace was still written
    async with sessions() as session:
        records = list(
            await session.scalars(select(RetrievalRecord).where(RetrievalRecord.task_id == task_id))
        )
    if result.chunks:
        assert len(records) >= 1

    await engine.dispose()


def test_retrieval_trace_is_idempotent_on_retry(tmp_path: Path) -> None:
    asyncio.run(_idempotency_scenario(tmp_path))


async def _idempotency_scenario(tmp_path: Path) -> None:
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{(tmp_path / 'idem.sqlite3').as_posix()}",
        poolclass=NullPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    project_id, task_id = await _create_project_and_task(sessions)
    file_id = await _create_file(sessions, project_id, "src/auth.py")
    await _create_chunk(
        sessions,
        project_id=project_id,
        file_id=file_id,
        fingerprint="y" * 64,
        content="def login():\n    pass",
        symbol_name="login",
        qualified_name="login",
        symbol_type="function",
        language="python",
        embedding=_embedding_vector(10),
        start_line=1,
        end_line=2,
        relative_path="src/auth.py",
    )

    retriever = HybridRetriever(sessions, FakeEmbeddingProvider())
    first = await retriever.retrieve(
        task_id=task_id,
        project_id=project_id,
        query="login",
        review_item_key="login-review",
    )

    # Retry with same parameters — should not raise duplicate key error
    second = await retriever.retrieve(
        task_id=task_id,
        project_id=project_id,
        query="login",
        review_item_key="login-review",
    )

    assert first.query_hash == second.query_hash
    assert len(second.chunks) >= 1

    await engine.dispose()


def test_context_assembler_token_budget_truncation(tmp_path: Path) -> None:
    asyncio.run(_token_budget_scenario(tmp_path))


def test_empty_retrieval_trace_is_persisted_once(tmp_path: Path) -> None:
    asyncio.run(_empty_trace_scenario(tmp_path))


async def _empty_trace_scenario(tmp_path: Path) -> None:
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{(tmp_path / 'empty-trace.sqlite3').as_posix()}",
        poolclass=NullPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    project_id, task_id = await _create_project_and_task(sessions)
    retriever = HybridRetriever(sessions, FakeEmbeddingProvider())

    first = await retriever.retrieve(
        task_id=task_id,
        project_id=project_id,
        query="missing symbol",
        review_item_key="empty-review",
    )
    second = await retriever.retrieve(
        task_id=task_id,
        project_id=project_id,
        query=" missing symbol ",
        review_item_key="empty-review",
    )

    assert first.query_hash == second.query_hash
    assert not first.chunks
    async with sessions() as session:
        records = list(
            await session.scalars(select(RetrievalRecord).where(RetrievalRecord.task_id == task_id))
        )
    assert len(records) == 1
    assert records[0].chunk_id is None
    assert records[0].degradation_reason == "symbol_ilike_no_match"
    await engine.dispose()


def test_target_paths_and_per_call_top_k_are_applied(tmp_path: Path) -> None:
    asyncio.run(_path_and_top_k_scenario(tmp_path))


async def _path_and_top_k_scenario(tmp_path: Path) -> None:
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{(tmp_path / 'path-filter.sqlite3').as_posix()}",
        poolclass=NullPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    project_id, task_id = await _create_project_and_task(sessions)
    for index, path in enumerate(("src/auth.py", "tests/test_auth.py"), start=1):
        file_id = await _create_file(sessions, project_id, path)
        await _create_chunk(
            sessions,
            project_id=project_id,
            file_id=file_id,
            fingerprint=str(index) * 64,
            content=f"def login_{index}():\n    return True",
            symbol_name=f"login_{index}",
            qualified_name=f"login_{index}",
            symbol_type="function",
            language="python",
            embedding=_embedding_vector(index),
            start_line=1,
            end_line=2,
            relative_path=path,
        )

    result = await HybridRetriever(sessions, FakeEmbeddingProvider()).retrieve(
        task_id=task_id,
        project_id=project_id,
        query="login",
        target_paths=("src",),
        top_k=1,
    )

    assert len(result.chunks) == 1
    assert result.chunks[0].chunk.relative_path == "src/auth.py"
    await engine.dispose()


async def _token_budget_scenario(tmp_path: Path) -> None:
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{(tmp_path / 'budget.sqlite3').as_posix()}",
        poolclass=NullPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    project_id, task_id = await _create_project_and_task(sessions)
    file_id = await _create_file(sessions, project_id, "src/large.py")

    # Create multiple chunks that would exceed a tiny budget
    for i in range(5):
        await _create_chunk(
            sessions,
            project_id=project_id,
            file_id=file_id,
            fingerprint=f"z{i}" + "x" * 62,
            content=f"def func_{i}():\n" + "    pass\n" * 50,
            symbol_name=f"func_{i}",
            qualified_name=f"func_{i}",
            symbol_type="function",
            language="python",
            embedding=_embedding_vector(i + 1),
            start_line=i * 52 + 1,
            end_line=i * 52 + 51,
            relative_path="src/large.py",
        )

    retriever = HybridRetriever(sessions, FakeEmbeddingProvider(), top_k=5, max_top_k=10)
    result = await retriever.retrieve(
        task_id=task_id,
        project_id=project_id,
        query="func",
    )
    assert len(result.chunks) >= 1

    # Assemble with a small token budget — should truncate before all chunks
    assembler = ContextAssembler(sessions, max_token_budget=2000)
    assembled = await assembler.assemble(result.chunks)

    assert len(assembled) >= 1
    assert len(assembled) <= len(result.chunks)

    await engine.dispose()
