"""Orchestrated hybrid retrieval with vector, keyword, RRF, trace, and degradation."""

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from hashlib import sha256

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.indexing.provider import EmbeddingProvider, EmbeddingProviderError
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
    """Embed the query once, run both searches, fuse with RRF, and persist trace.

    Degradation chain (per spec §11.4):
        Embedding failure  → keyword-only (after one retry)
        Vector search failure → keyword-only
        Keyword search failure → empty result with degradation recorded
    """

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        provider: EmbeddingProvider,
        *,
        rrf_k: int = 60,
        top_k: int = 10,
        max_top_k: int = 30,
    ) -> None:
        if top_k < 1 or max_top_k < top_k:
            raise ValueError("Require 1 <= top_k <= max_top_k")
        self._sessions = sessions
        self._provider = provider
        self._rrf_k = rrf_k
        self._top_k = top_k
        self._max_top_k = max_top_k
        self._vector = VectorSearcher()
        self._keyword = KeywordSearcher()

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def retrieve(
        self,
        *,
        task_id: int,
        project_id: int,
        query: str,
        languages: Sequence[str] = ("java", "python"),
        review_item_key: str | None = None,
        retrieval_round: int = 1,
    ) -> HybridRetrievalResult:
        """Run hybrid retrieval, degrade gracefully, and write trace."""
        if not query.strip():
            return HybridRetrievalResult(
                chunks=(),
                query_hash="",
                vector_results=(),
                keyword_results=(),
            )

        query_hash = sha256(query.encode("utf-8")).hexdigest()
        query_preview = query.strip()[:256]
        # Normalise NULL to empty string so the DB unique constraint works.
        item_key = review_item_key or ""

        # --- Degradation chain: embedding (with one retry) ---
        query_vector = await self._embed_query(query)
        if query_vector is None:
            return await self._keyword_only(
                task_id=task_id,
                project_id=project_id,
                query=query,
                query_hash=query_hash,
                query_preview=query_preview,
                languages=languages,
                review_item_key=item_key,
                retrieval_round=retrieval_round,
                degradation_reason="embedding_failed",
            )

        # --- Vector + Keyword parallel search (single session) ---
        async with self._sessions() as session:
            vector_raw = await self._vector_search(session, query_vector, project_id, languages)
            keyword_raw = await self._keyword_search(session, query, project_id, languages)

            # --- Degradation: both failed ---
            if vector_raw is None and keyword_raw is None:
                return HybridRetrievalResult(
                    chunks=(),
                    query_hash=query_hash,
                    vector_results=(),
                    keyword_results=(),
                    degradation=("vector_search_failed", "keyword_search_failed"),
                )

            # --- Degradation: vector failed → keyword-only ---
            if vector_raw is None:
                return await self._build_and_trace(
                    session=session,
                    task_id=task_id,
                    project_id=project_id,
                    query_hash=query_hash,
                    query_preview=query_preview,
                    review_item_key=item_key,
                    retrieval_round=retrieval_round,
                    vector_raw=[],
                    keyword_raw=keyword_raw or [],
                    top_k_override=self._top_k,
                    degradation_reason="vector_search_failed",
                )

            # --- Degradation: keyword failed → vector-only via RRF ---
            if keyword_raw is None:
                fused = fuse_rrf([vector_raw], k=self._rrf_k, top_k=self._top_k)
                scored = await self._load_and_score(session, vector_raw, [], fused)
                await self._write_trace(
                    task_id=task_id,
                    project_id=project_id,
                    review_item_key=item_key,
                    query_hash=query_hash,
                    query_preview=query_preview,
                    vector_raw=vector_raw,
                    keyword_raw=[],
                    fused=fused,
                    retrieval_round=retrieval_round,
                )
                return HybridRetrievalResult(
                    chunks=scored,
                    query_hash=query_hash,
                    vector_results=tuple(vector_raw),
                    keyword_results=(),
                    degradation=("keyword_search_failed",),
                )

            # --- Normal path: RRF fusion ---
            fused = fuse_rrf(
                [vector_raw, keyword_raw],
                k=self._rrf_k,
                top_k=self._top_k,
            )
            scored = await self._load_and_score(session, vector_raw, keyword_raw, fused)

        await self._write_trace(
            task_id=task_id,
            project_id=project_id,
            review_item_key=item_key,
            query_hash=query_hash,
            query_preview=query_preview,
            vector_raw=vector_raw,
            keyword_raw=keyword_raw,
            fused=fused,
            retrieval_round=retrieval_round,
        )

        return HybridRetrievalResult(
            chunks=scored,
            query_hash=query_hash,
            vector_results=tuple(vector_raw),
            keyword_results=tuple(keyword_raw),
        )

    # ------------------------------------------------------------------
    # Degradation helpers
    # ------------------------------------------------------------------

    async def _embed_query(self, query: str) -> list[float] | None:
        """Embed with one retry; return None on persistent failure."""
        for attempt in (1, 2):
            try:
                vectors = await self._provider.embed([query.strip()], text_type="query")
                if vectors and len(vectors[0]) == self._provider.dimension:
                    return vectors[0]
                if attempt == 1:
                    logger.warning("retrieval_embedding_invalid_response_retry")
                    continue
                logger.warning("retrieval_embedding_invalid_response")
                return None
            except (EmbeddingProviderError, Exception) as exc:
                if attempt == 1:
                    logger.warning("retrieval_embedding_retry", extra={"error": str(exc)[:128]})
                    continue
                logger.warning("retrieval_embedding_failed", extra={"error": str(exc)[:128]})
                return None
        return None

    async def _vector_search(
        self,
        session: AsyncSession,
        query_vector: list[float],
        project_id: int,
        languages: Sequence[str],
    ) -> list[tuple[int, float]] | None:
        """Run vector search; return None on failure so caller can degrade."""
        try:
            return await self._vector.search(
                session,
                query_vector=query_vector,
                project_id=project_id,
                languages=languages,
                top_k=self._max_top_k,
            )
        except Exception as exc:
            logger.warning("retrieval_vector_search_failed", extra={"error": str(exc)[:128]})
            return None

    async def _keyword_search(
        self,
        session: AsyncSession,
        query: str,
        project_id: int,
        languages: Sequence[str],
    ) -> list[tuple[int, float]] | None:
        """Run keyword search; return None on failure so caller can degrade."""
        try:
            return await self._keyword.search(
                session,
                query=query.strip(),
                project_id=project_id,
                languages=languages,
                top_k=self._max_top_k,
            )
        except Exception as exc:
            logger.warning("retrieval_keyword_search_failed", extra={"error": str(exc)[:128]})
            return None

    async def _keyword_only(
        self,
        *,
        task_id: int,
        project_id: int,
        query: str,
        query_hash: str,
        query_preview: str,
        languages: Sequence[str],
        review_item_key: str,
        retrieval_round: int,
        degradation_reason: str,
    ) -> HybridRetrievalResult:
        """Fallback: keyword-only retrieval when embedding or vector search fails."""
        async with self._sessions() as session:
            keyword_raw = await self._keyword_search(session, query, project_id, languages)

        if keyword_raw is None:
            return HybridRetrievalResult(
                chunks=(),
                query_hash=query_hash,
                vector_results=(),
                keyword_results=(),
                degradation=(degradation_reason, "keyword_search_failed"),
            )

        if not keyword_raw:
            return HybridRetrievalResult(
                chunks=(),
                query_hash=query_hash,
                vector_results=(),
                keyword_results=(),
                degradation=(degradation_reason,),
            )

        async with self._sessions() as session:
            fused = keyword_raw[: self._top_k]
            scored = await self._load_and_score(session, [], keyword_raw, fused)

        await self._write_trace(
            task_id=task_id,
            project_id=project_id,
            review_item_key=review_item_key,
            query_hash=query_hash,
            query_preview=query_preview,
            vector_raw=[],
            keyword_raw=keyword_raw,
            fused=fused,
            retrieval_round=retrieval_round,
        )

        return HybridRetrievalResult(
            chunks=scored,
            query_hash=query_hash,
            vector_results=(),
            keyword_results=tuple(keyword_raw),
            degradation=(degradation_reason,),
        )

    async def _build_and_trace(
        self,
        *,
        session: AsyncSession,
        task_id: int,
        project_id: int,
        query_hash: str,
        query_preview: str,
        review_item_key: str,
        retrieval_round: int,
        vector_raw: list[tuple[int, float]],
        keyword_raw: list[tuple[int, float]],
        top_k_override: int,
        degradation_reason: str,
    ) -> HybridRetrievalResult:
        """Build scored chunks + trace inside the caller's session."""
        fused = keyword_raw[:top_k_override]
        scored = await self._load_and_score(session, [], keyword_raw, fused)

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
        )

        return HybridRetrievalResult(
            chunks=scored,
            query_hash=query_hash,
            vector_results=tuple(vector_raw),
            keyword_results=tuple(keyword_raw),
            degradation=(degradation_reason,),
        )

    # ------------------------------------------------------------------
    # Shared helpers (all session-safe)
    # ------------------------------------------------------------------

    async def _load_and_score(
        self,
        session: AsyncSession,
        vector_raw: list[tuple[int, float]],
        keyword_raw: list[tuple[int, float]],
        fused: list[tuple[int, float]],
    ) -> tuple[ScoredChunk, ...]:
        """Load chunks and build ScoredChunk objects using a live session."""
        chunk_ids = [chunk_id for chunk_id, _ in fused]
        chunks = await self._load_chunks(session, chunk_ids, fused)

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

    async def _load_chunks(
        self,
        session: AsyncSession,
        ids: list[int],
        fused: list[tuple[int, float]],
    ) -> dict[int, CodeChunk]:
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
    ) -> None:
        """Write trace records; IntegrityError (duplicate) is silently tolerated."""
        selected_ids = {chunk_id for chunk_id, _ in fused}
        vector_ranks = self._rank_map(vector_raw)
        keyword_ranks = self._rank_map(keyword_raw)
        all_ids = {chunk_id for chunk_id, _ in vector_raw} | {
            chunk_id for chunk_id, _ in keyword_raw
        }

        if not all_ids:
            return

        try:
            async with self._sessions.begin() as session:
                for chunk_id in all_ids:
                    session.add(
                        RetrievalRecord(
                            task_id=task_id,
                            project_id=project_id,
                            review_item_key=review_item_key,
                            query_hash=query_hash,
                            query_preview=query_preview,
                            chunk_id=chunk_id,
                            vector_rank=vector_ranks.get(chunk_id),
                            keyword_rank=keyword_ranks.get(chunk_id),
                            rrf_score=dict(fused).get(chunk_id),
                            selected=chunk_id in selected_ids,
                            retrieval_round=retrieval_round,
                        )
                    )
        except IntegrityError:
            await session.rollback()
            logger.debug(
                "retrieval_trace_duplicate_skipped",
                extra={"task_id": task_id, "query_hash": query_hash},
            )

    @staticmethod
    def _rank_map(ranked: list[tuple[int, float]]) -> dict[int, int]:
        return {item_id: pos for pos, (item_id, _) in enumerate(ranked, start=1)}
