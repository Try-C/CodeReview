"""PostgreSQL full-text keyword search on code_chunks with SQLite and ILIKE fallback."""

from collections.abc import Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# ts_rank with normalization bit 2 (divide by document length) keeps short
# chunks from being systematically outranked by very long ones.
KEYWORD_SQL = """
    SELECT id, ts_rank(search_vector, plainto_tsquery('simple', :query), 2) AS rank
    FROM code_chunks
    WHERE project_id = :project_id
      AND language = ANY(:languages)
      AND index_status = 'ready'
      AND search_vector IS NOT NULL
    ORDER BY rank DESC
    LIMIT :top_k
"""

# SQLite fallback: LIKE-based search on search_text which stores the raw
# content and identifiers.  The rank is a simple term-occurrence count divided
# by 100 so it stays numerically comparable with ts_rank values (~0-1 range).
FALLBACK_SQL = """
    SELECT id,
           (LENGTH(search_text) - LENGTH(REPLACE(LOWER(search_text), LOWER(:term), '')))
           * 1.0 / LENGTH(:term) / 100.0 AS rank
    FROM code_chunks
    WHERE project_id = :project_id
      AND language IN ({language_placeholders})
      AND index_status = 'ready'
      AND LOWER(search_text) LIKE '%' || LOWER(:term) || '%'
    ORDER BY rank DESC
    LIMIT :top_k
"""

# Last-resort ILIKE fallback: match individual query terms against
# symbol_name and qualified_name columns (spec 11.4 symbol/ILIKE).
ILIKE_SYMBOL_SQL = """
    SELECT id, 0.01 AS rank
    FROM code_chunks
    WHERE project_id = :project_id
      AND language IN ({language_placeholders})
      AND index_status = 'ready'
      AND (
        LOWER(symbol_name) LIKE '%' || LOWER(:term) || '%'
        OR LOWER(qualified_name) LIKE '%' || LOWER(:term) || '%'
      )
    ORDER BY id
    LIMIT :top_k
"""


class KeywordSearcher:
    """Search the PostgreSQL full-text index with progressive fallbacks.

    Degradation order (per spec 11.4):
        1. PostgreSQL tsvector / ts_rank
        2. SQLite LIKE on search_text
        3. ILIKE on symbol_name / qualified_name (last resort)
    """

    async def search(
        self,
        session: AsyncSession,
        *,
        query: str,
        project_id: int,
        languages: Sequence[str] = ("java", "python"),
        top_k: int = 10,
    ) -> list[tuple[int, float]]:
        """Return (chunk_id, rank) ordered by descending relevance."""
        if top_k < 1 or not query.strip():
            return []

        dialect_name = session.bind.dialect.name if session.bind is not None else "postgresql"

        if dialect_name == "postgresql":
            return await self._search_postgresql(session, query, project_id, languages, top_k)
        return await self._search_fallback(session, query, project_id, languages, top_k)

    async def search_symbol_ilike(
        self,
        session: AsyncSession,
        *,
        query: str,
        project_id: int,
        languages: Sequence[str] = ("java", "python"),
        top_k: int = 10,
    ) -> list[tuple[int, float]]:
        """Last-resort ILIKE match on symbol_name / qualified_name (spec 11.4)."""
        if top_k < 1 or not query.strip():
            return []

        lang_list = list(languages)
        placeholders = ", ".join(f":lang_{i}" for i in range(len(lang_list)))
        params: dict[str, object] = {
            "term": query.strip().split()[0] if query.strip() else query.strip(),
            "project_id": project_id,
            "top_k": top_k,
        }
        for i, lang in enumerate(lang_list):
            params[f"lang_{i}"] = lang

        result = await session.execute(
            text(ILIKE_SYMBOL_SQL.format(language_placeholders=placeholders)),
            params,
        )
        return [(int(row.id), float(row.rank)) for row in result]

    async def _search_postgresql(
        self,
        session: AsyncSession,
        query: str,
        project_id: int,
        languages: Sequence[str],
        top_k: int,
    ) -> list[tuple[int, float]]:
        result = await session.execute(
            text(KEYWORD_SQL),
            {
                "query": query.strip(),
                "project_id": project_id,
                "languages": list(languages),
                "top_k": top_k,
            },
        )
        return [(int(row.id), float(row.rank)) for row in result]

    async def _search_fallback(
        self,
        session: AsyncSession,
        query: str,
        project_id: int,
        languages: Sequence[str],
        top_k: int,
    ) -> list[tuple[int, float]]:
        lang_list = list(languages)
        placeholders = ", ".join(f":lang_{i}" for i in range(len(lang_list)))
        params: dict[str, object] = {
            "term": query.strip().split()[0] if query.strip() else query.strip(),
            "project_id": project_id,
            "top_k": top_k,
        }
        for i, lang in enumerate(lang_list):
            params[f"lang_{i}"] = lang

        result = await session.execute(
            text(FALLBACK_SQL.format(language_placeholders=placeholders)),
            params,
        )
        return [(int(row.id), float(row.rank)) for row in result]
