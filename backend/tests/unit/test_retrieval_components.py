"""Unit tests for RRF, vector search, keyword search, and context assembly."""

import asyncio
from collections.abc import Coroutine
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from app.retrieval import fuse_rrf


def _run(coro: Coroutine[Any, Any, Any]) -> Any:
    return asyncio.run(coro)


class TestReciprocalRankFusion:
    def test_fuse_two_complete_lists(self) -> None:
        vector = [(1, 0.95), (2, 0.80), (3, 0.60)]
        keyword = [(2, 0.90), (3, 0.70), (1, 0.50)]

        fused = fuse_rrf([vector, keyword], k=60, top_k=3)

        ids = [item_id for item_id, _ in fused]
        assert ids == [2, 1, 3]

    def test_missing_from_one_list_contributes_zero(self) -> None:
        vector = [(1, 0.95)]
        keyword = [(2, 0.90)]

        fused = fuse_rrf([vector, keyword], k=60, top_k=3)

        ids = [item_id for item_id, _ in fused]
        assert 1 in ids
        assert 2 in ids

    def test_single_list_passthrough(self) -> None:
        ranked = [(5, 0.99), (7, 0.50)]
        fused = fuse_rrf([ranked], k=60, top_k=5)
        assert [item_id for item_id, _ in fused] == [5, 7]

    def test_empty_input_returns_empty(self) -> None:
        assert fuse_rrf([], k=60) == []

    def test_all_empty_lists_returns_empty(self) -> None:
        assert fuse_rrf([[], []], k=60) == []

    def test_top_k_truncation(self) -> None:
        items = [(i, 1.0) for i in range(20)]
        assert len(fuse_rrf([items], k=60, top_k=5)) == 5

    def test_different_k_values_affect_relative_weight(self) -> None:
        ranked = [(1, 1.0), (2, 0.9)]
        small_k = fuse_rrf([ranked], k=1, top_k=2)
        large_k = fuse_rrf([ranked], k=1000, top_k=2)
        assert small_k != large_k


class TestVectorSearcher:
    @staticmethod
    def _pg_session() -> AsyncMock:
        session = AsyncMock()
        bind_mock = MagicMock()
        bind_mock.dialect.name = "postgresql"
        session.bind = bind_mock
        return session

    def test_returns_empty_for_zero_top_k(self) -> None:
        from app.retrieval.vector_search import VectorSearcher

        searcher = VectorSearcher()
        result = _run(
            searcher.search(AsyncMock(), query_vector=[0.1] * 1024, project_id=1, top_k=0)
        )
        assert result == []

    def test_applies_hnsw_options_before_query(self) -> None:
        from app.retrieval.vector_search import VectorSearcher

        searcher = VectorSearcher()
        session = self._pg_session()
        session.execute = AsyncMock(return_value=MagicMock())
        session.execute.return_value = []

        _run(searcher.search(session, query_vector=[0.1] * 1024, project_id=1, top_k=10))
        assert session.execute.called


class TestKeywordSearcher:
    def test_returns_empty_for_zero_top_k(self) -> None:
        from app.retrieval.keyword_search import KeywordSearcher

        searcher = KeywordSearcher()
        session = AsyncMock()
        result = _run(searcher.search(session, query="find user", project_id=1, top_k=0))
        assert result == []

    def test_returns_empty_for_blank_query(self) -> None:
        from app.retrieval.keyword_search import KeywordSearcher

        searcher = KeywordSearcher()
        session = AsyncMock()
        result = _run(searcher.search(session, query="   ", project_id=1, top_k=10))
        assert result == []
