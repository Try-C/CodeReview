"""Orchestrated hybrid retrieval with vector, keyword, RRF, and trace."""

from collections.abc import Sequence
from dataclasses import dataclass
from hashlib import sha256

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.indexing.provider import EmbeddingProvider
from app.models.index import CodeChunk
from app.models.retrieval import RetrievalRecord
from app.retrieval.keyword_search import KeywordSearcher
from app.retrieval.rrf import fuse_rrf
from app.retrieval.vector_search import VectorSearcher


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


class HybridRetriever:
    """Embed the query once, run both searches, fuse with RRF, and persist trace."""

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
        """Run hybrid retrieval and write an immutable trace record."""
        if not query.strip():
            return HybridRetrievalResult(
                chunks=(),
                query_hash="",
                vector_results=(),
                keyword_results=(),
            )

        query_hash = sha256(query.encode("utf-8")).hexdigest()
        query_preview = query.strip()[:256]

        query_vector = await self._provider.embed(
            [query.strip()],
            text_type="query",
        )

        async with self._sessions() as session:
            vector_raw = await self._vector.search(
                session,
                query_vector=query_vector[0],
                project_id=project_id,
                languages=languages,
                top_k=self._max_top_k,
            )
            keyword_raw = await self._keyword.search(
                session,
                query=query.strip(),
                project_id=project_id,
                languages=languages,
                top_k=self._max_top_k,
            )

            fused = fuse_rrf(
                [vector_raw, keyword_raw],
                k=self._rrf_k,
                top_k=self._top_k,
            )

            chunk_ids = [chunk_id for chunk_id, _ in fused]
            chunks = await self._load_chunks(session, chunk_ids, fused)

            vector_ranks = self._rank_map(vector_raw)
            keyword_ranks = self._rank_map(keyword_raw)

            scored = tuple(
                ScoredChunk(
                    chunk=chunks[chunk_id],
                    rrf_score=score,
                    vector_rank=vector_ranks.get(chunk_id),
                    keyword_rank=keyword_ranks.get(chunk_id),
                )
                for chunk_id, score in fused
                if chunk_id in chunks
            )

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
        )

    async def _load_chunks(
        self,
        session: AsyncSession,
        ids: list[int],
        fused: list[tuple[int, float]],
    ) -> dict[int, CodeChunk]:
        from sqlalchemy import select as sa_select

        rows = await session.scalars(
            sa_select(CodeChunk).where(CodeChunk.id.in_(ids))
        )
        return {chunk.id: chunk for chunk in rows}

    async def _write_trace(
        self,
        *,
        task_id: int,
        project_id: int,
        review_item_key: str | None,
        query_hash: str,
        query_preview: str,
        vector_raw: list[tuple[int, float]],
        keyword_raw: list[tuple[int, float]],
        fused: list[tuple[int, float]],
        retrieval_round: int,
    ) -> None:
        selected_ids = {chunk_id for chunk_id, _ in fused}
        vector_ranks = self._rank_map(vector_raw)
        keyword_ranks = self._rank_map(keyword_raw)
        all_ids = {chunk_id for chunk_id, _ in vector_raw} | {
            chunk_id for chunk_id, _ in keyword_raw
        }

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

    @staticmethod
    def _rank_map(ranked: list[tuple[int, float]]) -> dict[int, int]:
        return {item_id: pos for pos, (item_id, _) in enumerate(ranked, start=1)}
