"""Incremental indexing integration coverage with a fake provider."""

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.database import Base
from app.indexing import EmbeddingProviderError, IndexingService
from app.languages import ParsedChunk, ParseResult, SymbolRef
from app.models import CodeChunk, CodeRelation, CodeSymbol, Project, ProjectFile, User


@dataclass(slots=True)
class FakeEmbeddingProvider:
    model: str = "text-embedding-v4"
    dimension: int = 1024
    error: EmbeddingProviderError | None = None
    calls: list[tuple[tuple[str, ...], str]] = field(default_factory=list)

    async def embed(
        self,
        texts: Sequence[str],
        *,
        text_type: Literal["document", "query"],
    ) -> list[list[float]]:
        self.calls.append((tuple(texts), text_type))
        if self.error is not None:
            raise self.error
        return [[float(index + 1)] * self.dimension for index, _ in enumerate(texts)]


class FixedTokenCounter:
    def __init__(self, count: int) -> None:
        self._count = count

    def count(self, text: str) -> int:
        del text
        return self._count


def _parse_result(
    *,
    fingerprint: str,
    start_line: int = 1,
    parser_version: str = "1",
) -> ParseResult:
    chunk = ParsedChunk(
        file_path="src/service.py",
        language="python",
        symbol_type="function",
        symbol_name="review",
        qualified_name="review",
        signature="review(value)",
        start_line=start_line,
        end_line=start_line + 1,
        content="def review(value):\n    return sanitize(value)",
        imports=("security.sanitize",),
        content_hash="c" * 64,
        chunk_fingerprint=fingerprint,
        parser_version=parser_version,
    )
    return ParseResult(
        language="python",
        file_path=chunk.file_path,
        chunks=(chunk,),
        symbol_refs=(
            SymbolRef(
                source_symbol="review",
                target_symbol="sanitize",
                source_file=chunk.file_path,
                relation_type="call",
                confidence=0.8,
            ),
        ),
    )


def test_indexing_is_incremental_and_persists_keyword_search(tmp_path: Path) -> None:
    asyncio.run(_incremental_scenario(tmp_path))


async def _incremental_scenario(tmp_path: Path) -> None:
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{(tmp_path / 'index.sqlite3').as_posix()}",
        poolclass=NullPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    project_id, file_id = await _create_project_file(sessions)
    provider = FakeEmbeddingProvider()
    service = IndexingService(sessions, provider)

    first = await service.index_file(
        project_id=project_id,
        file_id=file_id,
        file_hash="file-v1",
        parse_result=_parse_result(fingerprint="a" * 64),
    )
    retry = await service.index_file(
        project_id=project_id,
        file_id=file_id,
        file_hash="file-v1",
        parse_result=_parse_result(fingerprint="a" * 64),
    )
    reparsed = await service.index_file(
        project_id=project_id,
        file_id=file_id,
        file_hash="file-v1",
        parse_result=_parse_result(fingerprint="a" * 64, parser_version="2"),
    )
    moved = await service.index_file(
        project_id=project_id,
        file_id=file_id,
        file_hash="file-v2",
        parse_result=_parse_result(fingerprint="b" * 64, start_line=4),
    )

    async with sessions() as session:
        chunks = list(await session.scalars(select(CodeChunk)))
        symbols = list(await session.scalars(select(CodeSymbol)))
        relations = list(await session.scalars(select(CodeRelation)))

    assert first.embedded_chunks == 1
    assert retry.reused_file
    assert not reparsed.reused_file
    assert reparsed.reused_embeddings == 1
    assert moved.reused_embeddings == 1
    assert len(provider.calls) == 1
    assert provider.calls[0][1] == "document"
    assert len(chunks) == len(symbols) == len(relations) == 1
    assert chunks[0].chunk_fingerprint == "b" * 64
    assert chunks[0].embedding_status == "ready"
    assert chunks[0].search_vector
    assert "review" in chunks[0].search_text
    assert relations[0].resolution_status == "unresolved"

    await engine.dispose()


def test_provider_failure_and_token_limit_degrade_to_keyword_only(
    tmp_path: Path,
) -> None:
    asyncio.run(_degradation_scenario(tmp_path))


async def _degradation_scenario(tmp_path: Path) -> None:
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{(tmp_path / 'degrade.sqlite3').as_posix()}",
        poolclass=NullPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    project_id, first_file = await _create_project_file(sessions)
    provider = FakeEmbeddingProvider(error=EmbeddingProviderError("UPSTREAM_UNAVAILABLE"))
    service = IndexingService(sessions, provider)

    failed = await service.index_file(
        project_id=project_id,
        file_id=first_file,
        file_hash="file-failed",
        parse_result=_parse_result(fingerprint="d" * 64),
    )

    async with sessions.begin() as session:
        second = ProjectFile(
            project_id=project_id,
            relative_path="src/second.py",
            scan_status="included",
        )
        session.add(second)
        await session.flush()
        second_file = second.id
    oversized_result = _parse_result(fingerprint="e" * 64)
    oversized_chunk = oversized_result.chunks[0]
    second_result = ParseResult(
        language="python",
        file_path="src/second.py",
        chunks=(
            ParsedChunk(
                file_path="src/second.py",
                language=oversized_chunk.language,
                symbol_type=oversized_chunk.symbol_type,
                symbol_name=oversized_chunk.symbol_name,
                start_line=1,
                end_line=2,
                content=oversized_chunk.content,
                content_hash="f" * 64,
                chunk_fingerprint="e" * 64,
            ),
        ),
    )
    oversized_service = IndexingService(
        sessions,
        FakeEmbeddingProvider(),
        token_counter=FixedTokenCounter(8193),
    )
    oversized = await oversized_service.index_file(
        project_id=project_id,
        file_id=second_file,
        file_hash="file-oversized",
        parse_result=second_result,
    )

    async with sessions() as session:
        chunks = list(await session.scalars(select(CodeChunk).order_by(CodeChunk.file_id)))

    assert failed.keyword_only_chunks == oversized.keyword_only_chunks == 1
    assert chunks[0].embedding_error == "UPSTREAM_UNAVAILABLE"
    assert chunks[1].embedding_error == "EMBEDDING_INPUT_TOKEN_LIMIT"
    assert all(chunk.index_status == "ready" for chunk in chunks)
    assert all(chunk.search_vector for chunk in chunks)

    await engine.dispose()


async def _create_project_file(
    sessions: async_sessionmaker[AsyncSession],
) -> tuple[int, int]:
    async with sessions.begin() as session:
        user = User(username=f"index-user-{id(session)}", password_hash="not-used")
        session.add(user)
        await session.flush()
        project = Project(
            user_id=user.id,
            project_name="index-project",
            storage_key=f"{id(session):032x}"[-32:],
        )
        session.add(project)
        await session.flush()
        project_file = ProjectFile(
            project_id=project.id,
            relative_path="src/service.py",
            scan_status="included",
        )
        session.add(project_file)
        await session.flush()
        return project.id, project_file.id
