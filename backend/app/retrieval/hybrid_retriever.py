"""Orchestrated hybrid retrieval with independent degradation and durable trace."""

import asyncio
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from hashlib import sha256

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.indexing.provider import EmbeddingProvider
from app.models.index import CodeChunk
from app.models.retrieval import RetrievalRecord
from app.retrieval.keyword_search import KeywordSearcher
from app.retrieval.rrf import fuse_rrf
from app.retrieval.vector_search import VectorSearcher

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ScoredChunk:
    """A retrieved chunk with its fusion score and per-source ranks."""

    chunk: CodeChunk
    rrf_score: float
    vector_rank: int | None
    keyword_rank: int | None


@dataclass(frozen=True, slots=True)
class HybridRetrievalResult:
    """Complete outcome of one hybrid search including trace data."""

    chunks: tuple[ScoredChunk, ...]
    query_hash: str
    vector_results: tuple[tuple[int, float], ...]
    keyword_results: tuple[tuple[int, float], ...]
    degradation: tuple[str, ...] = ()


class HybridRetriever:
    """Embed once, search independently, fuse with RRF, and persist trace."""

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        provider: EmbeddingProvider,
        *,
        rrf_k: int = 60,
        top_k: int = 10,
        max_top_k: int = 30,
        vector_searcher: VectorSearcher | None = None,
        keyword_searcher: KeywordSearcher | None = None,
    ) -> None:
        if rrf_k < 1:
            raise ValueError("rrf_k must be positive")
        if top_k < 1 or max_top_k < top_k:
            raise ValueError("Require 1 <= top_k <= max_top_k")
        self._sessions = sessions
        self._provider = provider
        self._rrf_k = rrf_k
        self._top_k = top_k
        self._max_top_k = max_top_k
        self._vector = vector_searcher or VectorSearcher()
        self._keyword = keyword_searcher or KeywordSearcher()

    async def retrieve(
        self,
        *,
        task_id: int,
        project_id: int,
        query: str,
        languages: Sequence[str] = ("java", "python"),
        review_item_key: str | None = None,
        retrieval_round: int = 1,
        target_paths: Sequence[str] = (),
        top_k: int | None = None,
    ) -> HybridRetrievalResult:
        """Run hybrid retrieval with isolated search transactions."""
        normalized_query = query.strip()
        if not normalized_query:
            return HybridRetrievalResult(
                chunks=(),
                query_hash="",
                vector_results=(),
                keyword_results=(),
            )

        selected_top_k = self._top_k if top_k is None else top_k
        if selected_top_k < 1 or selected_top_k > self._max_top_k:
            raise ValueError(f"top_k must be between 1 and {self._max_top_k}")
        if retrieval_round < 1:
            raise ValueError("retrieval_round must be positive")

        item_key = review_item_key or ""
        if len(item_key) > 128:
            raise ValueError("review_item_key must not exceed 128 characters")

        normalized_paths = tuple(
            dict.fromkeys(path.strip().replace("\\", "/").rstrip("/") for path in target_paths)
        )
        normalized_paths = tuple(path for path in normalized_paths if path)
        query_hash = sha256(normalized_query.encode("utf-8")).hexdigest()
        query_preview = normalized_query[:256]

        query_vector = await self._embed_query(normalized_query)
        if query_vector is None:
            fallback_keyword_raw, fallback_degradation = await self._keyword_with_symbol_fallback(
                query=normalized_query,
                project_id=project_id,
                languages=languages,
                target_paths=normalized_paths,
            )
            return await self._finalize(
                task_id=task_id,
                project_id=project_id,
                review_item_key=item_key,
                query_hash=query_hash,
                query_preview=query_preview,
                retrieval_round=retrieval_round,
                vector_raw=[],
                keyword_raw=fallback_keyword_raw,
                top_k=selected_top_k,
                degradation=("embedding_failed", *fallback_degradation),
            )

        vector_task = asyncio.create_task(
            self._run_vector_search(
                query_vector,
                project_id,
                languages,
                normalized_paths,
            )
        )
        keyword_task = asyncio.create_task(
            self._run_keyword_search(
                normalized_query,
                project_id,
                languages,
                normalized_paths,
            )
        )
        vector_raw = await vector_task
        keyword_raw = await keyword_task

        degradation: list[str] = []
        vector_values = vector_raw or []
        keyword_values = keyword_raw or []
        if vector_raw is None:
            degradation.append("vector_search_failed")
        if keyword_raw is None:
            degradation.append("keyword_search_failed")

        # The vector degradation chain ends with a symbol-name fallback.
        if not keyword_values and (vector_raw is None or not vector_values):
            symbol_raw = await self._run_symbol_search(
                normalized_query,
                project_id,
                languages,
                normalized_paths,
            )
            if symbol_raw is None:
                degradation.append("symbol_search_failed")
            elif symbol_raw:
                keyword_values = symbol_raw
                degradation.append("symbol_ilike_fallback")
            else:
                degradation.append("symbol_ilike_no_match")

        if not vector_values and not keyword_values and not degradation:
            degradation.append("no_results")

        return await self._finalize(
            task_id=task_id,
            project_id=project_id,
            review_item_key=item_key,
            query_hash=query_hash,
            query_preview=query_preview,
            retrieval_round=retrieval_round,
            vector_raw=vector_values,
            keyword_raw=keyword_values,
            top_k=selected_top_k,
            degradation=tuple(degradation),
        )

    async def _embed_query(self, query: str) -> list[float] | None:
        """Embed with one retry; return None on persistent failure."""
        for attempt in (1, 2):
            try:
                vectors = await self._provider.embed([query], text_type="query")
                if vectors and len(vectors[0]) == self._provider.dimension:
                    return vectors[0]
                event = (
                    "retrieval_embedding_invalid_response_retry"
                    if attempt == 1
                    else "retrieval_embedding_invalid_response"
                )
                logger.warning(event)
            except Exception as exc:
                event = (
                    "retrieval_embedding_retry" if attempt == 1 else "retrieval_embedding_failed"
                )
                logger.warning(event, extra={"error": str(exc)[:128]})
        return None

    async def _run_vector_search(
        self,
        query_vector: list[float],
        project_id: int,
        languages: Sequence[str],
        target_paths: Sequence[str],
    ) -> list[tuple[int, float]] | None:
        try:
            async with self._sessions() as session:
                return await self._vector.search(
                    session,
                    query_vector=query_vector,
                    project_id=project_id,
                    languages=languages,
                    top_k=self._max_top_k,
                    target_paths=target_paths,
                )
        except Exception as exc:
            logger.warning("retrieval_vector_search_failed", extra={"error": str(exc)[:128]})
            return None

    async def _run_keyword_search(
        self,
        query: str,
        project_id: int,
        languages: Sequence[str],
        target_paths: Sequence[str],
    ) -> list[tuple[int, float]] | None:
        try:
            async with self._sessions() as session:
                return await self._keyword.search(
                    session,
                    query=query,
                    project_id=project_id,
                    languages=languages,
                    top_k=self._max_top_k,
                    target_paths=target_paths,
                )
        except Exception as exc:
            logger.warning("retrieval_keyword_search_failed", extra={"error": str(exc)[:128]})
            return None

    async def _run_symbol_search(
        self,
        query: str,
        project_id: int,
        languages: Sequence[str],
        target_paths: Sequence[str],
    ) -> list[tuple[int, float]] | None:
        try:
            # A fresh session is required if the full-text transaction failed.
            async with self._sessions() as session:
                return await self._keyword.search_symbol_ilike(
                    session,
                    query=query,
                    project_id=project_id,
                    languages=languages,
                    top_k=self._max_top_k,
                    target_paths=target_paths,
                )
        except Exception as exc:
            logger.warning("retrieval_symbol_search_failed", extra={"error": str(exc)[:128]})
            return None

    async def _keyword_with_symbol_fallback(
        self,
        *,
        query: str,
        project_id: int,
        languages: Sequence[str],
        target_paths: Sequence[str],
    ) -> tuple[list[tuple[int, float]], tuple[str, ...]]:
        keyword_raw = await self._run_keyword_search(
            query,
            project_id,
            languages,
            target_paths,
        )
        degradation: list[str] = []
        if keyword_raw is None:
            degradation.append("keyword_search_failed")
            keyword_raw = []
        if keyword_raw:
            return keyword_raw, tuple(degradation)

        symbol_raw = await self._run_symbol_search(
            query,
            project_id,
            languages,
            target_paths,
        )
        if symbol_raw is None:
            degradation.append("symbol_search_failed")
            return [], tuple(degradation)
        if symbol_raw:
            degradation.append("symbol_ilike_fallback")
            return symbol_raw, tuple(degradation)
        degradation.append("symbol_ilike_no_match")
        return [], tuple(degradation)

    async def _finalize(
        self,
        *,
        task_id: int,
        project_id: int,
        review_item_key: str,
        query_hash: str,
        query_preview: str,
        retrieval_round: int,
        vector_raw: list[tuple[int, float]],
        keyword_raw: list[tuple[int, float]],
        top_k: int,
        degradation: tuple[str, ...],
    ) -> HybridRetrievalResult:
        ranked_lists = [ranked for ranked in (vector_raw, keyword_raw) if ranked]
        fused = fuse_rrf(ranked_lists, k=self._rrf_k, top_k=top_k)

        async with self._sessions() as session:
            scored = await self._load_and_score(session, vector_raw, keyword_raw, fused)

        await self._write_trace(
            task_id=task_id,
            project_id=project_id,
            review_item_key=review_item_key,
            query_hash=query_hash,
            query_preview=query_preview,
            vector_raw=vector_raw,
            keyword_raw=keyword_raw,
            fused=fused,
            retrieval_round=retrieval_round,
            degradation=degradation,
        )
        return HybridRetrievalResult(
            chunks=scored,
            query_hash=query_hash,
            vector_results=tuple(vector_raw),
            keyword_results=tuple(keyword_raw),
            degradation=degradation,
        )

    async def _load_and_score(
        self,
        session: AsyncSession,
        vector_raw: list[tuple[int, float]],
        keyword_raw: list[tuple[int, float]],
        fused: list[tuple[int, float]],
    ) -> tuple[ScoredChunk, ...]:
        chunk_ids = [chunk_id for chunk_id, _ in fused]
        chunks = await self._load_chunks(session, chunk_ids)
        vector_ranks = self._rank_map(vector_raw)
        keyword_ranks = self._rank_map(keyword_raw)

        return tuple(
            ScoredChunk(
                chunk=chunks[chunk_id],
                rrf_score=score,
                vector_rank=vector_ranks.get(chunk_id),
                keyword_rank=keyword_ranks.get(chunk_id),
            )
            for chunk_id, score in fused
            if chunk_id in chunks
        )

    @staticmethod
    async def _load_chunks(
        session: AsyncSession,
        ids: list[int],
    ) -> dict[int, CodeChunk]:
        if not ids:
            return {}
        rows = await session.scalars(select(CodeChunk).where(CodeChunk.id.in_(ids)))
        return {chunk.id: chunk for chunk in rows}

    async def _write_trace(
        self,
        *,
        task_id: int,
        project_id: int,
        review_item_key: str,
        query_hash: str,
        query_preview: str,
        vector_raw: list[tuple[int, float]],
        keyword_raw: list[tuple[int, float]],
        fused: list[tuple[int, float]],
        retrieval_round: int,
        degradation: tuple[str, ...],
    ) -> None:
        """Insert candidate or empty-attempt traces without rolling back new rows."""
        selected_ids = {chunk_id for chunk_id, _ in fused}
        vector_ranks = self._rank_map(vector_raw)
        keyword_ranks = self._rank_map(keyword_raw)
        fused_scores = dict(fused)
        all_ids = sorted(set(vector_ranks) | set(keyword_ranks))
        degradation_reason = "|".join(degradation)[:255] or None

        trace_ids: list[int | None] = [chunk_id for chunk_id in all_ids] if all_ids else [None]
        values = [
            {
                "task_id": task_id,
                "project_id": project_id,
                "review_item_key": review_item_key,
                "query_hash": query_hash,
                "query_preview": query_preview,
                "chunk_id": chunk_id,
                "vector_rank": vector_ranks.get(chunk_id) if chunk_id is not None else None,
                "keyword_rank": keyword_ranks.get(chunk_id) if chunk_id is not None else None,
                "rrf_score": fused_scores.get(chunk_id) if chunk_id is not None else None,
                "selected": chunk_id in selected_ids if chunk_id is not None else False,
                "degradation_reason": degradation_reason,
                "retrieval_round": retrieval_round,
            }
            for chunk_id in trace_ids
        ]

        async with self._sessions.begin() as session:
            dialect = session.bind.dialect.name if session.bind is not None else "postgresql"
            if dialect == "sqlite":
                statement = sqlite_insert(RetrievalRecord).values(values)
                await session.execute(statement.on_conflict_do_nothing())
            else:
                postgresql_statement = postgresql_insert(RetrievalRecord).values(values)
                await session.execute(postgresql_statement.on_conflict_do_nothing())

    @staticmethod
    def _rank_map(ranked: list[tuple[int, float]]) -> dict[int, int]:
        return {item_id: pos for pos, (item_id, _) in enumerate(ranked, start=1)}
