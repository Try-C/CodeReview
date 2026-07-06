"""pgvector cosine-similarity search with transaction-local HNSW tuning."""

import json
import math
from collections.abc import Sequence

from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.indexing.database import HnswSearchOptions
from app.models.index import CodeChunk

VECTOR_COSINE_SQL = """
    SELECT id, 1 - (embedding <=> :query_vector::vector) AS similarity
    FROM code_chunks
    WHERE project_id = :project_id
      AND language = ANY(:languages)
      AND embedding IS NOT NULL
      AND embedding_status = 'ready'
      AND index_status = 'ready'
      {path_filter}
    ORDER BY embedding <=> :query_vector::vector
    LIMIT :top_k
"""


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute the cosine similarity between two dense vectors."""
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class VectorSearcher:
    """Search pgvector with cosine distance, respecting HNSW configuration."""

    def __init__(self, hnsw_options: HnswSearchOptions | None = None) -> None:
        self._hnsw = hnsw_options or HnswSearchOptions()

    async def search(
        self,
        session: AsyncSession,
        *,
        query_vector: list[float],
        project_id: int,
        languages: Sequence[str] = ("java", "python"),
        top_k: int = 10,
        target_paths: Sequence[str] = (),
    ) -> list[tuple[int, float]]:
        """Return (chunk_id, cosine_similarity) ordered by descending similarity."""
        if top_k < 1:
            return []

        dialect_name = session.bind.dialect.name if session.bind is not None else "postgresql"

        if dialect_name == "postgresql":
            await self._hnsw.apply(session)
            # pgvector expects the vector as a string like '[0.1, 0.2, ...]'
            vector_str = json.dumps(query_vector)
            params: dict[str, object] = {
                "query_vector": vector_str,
                "project_id": project_id,
                "languages": list(languages),
                "top_k": top_k,
            }
            path_filter = self._path_filter(target_paths, params)
            result = await session.execute(
                text(VECTOR_COSINE_SQL.format(path_filter=path_filter)),
                params,
            )
            return [(int(row.id), float(row.similarity)) for row in result]

        return await self._search_in_python(
            session,
            query_vector=query_vector,
            project_id=project_id,
            languages=languages,
            top_k=top_k,
            target_paths=target_paths,
        )

    async def _search_in_python(
        self,
        session: AsyncSession,
        *,
        query_vector: list[float],
        project_id: int,
        languages: Sequence[str],
        top_k: int,
        target_paths: Sequence[str],
    ) -> list[tuple[int, float]]:
        """Load ready chunks and compute cosine similarity in-process (SQLite)."""
        normalized_paths = [
            path.strip().replace("\\", "/").rstrip("/") for path in target_paths if path.strip()
        ]
        path_predicates = []
        for path in normalized_paths:
            escaped_path = path.replace("%", "\\%").replace("_", "\\_")
            path_predicates.append(
                or_(
                    CodeChunk.relative_path == path,
                    CodeChunk.relative_path.like(f"{escaped_path}/%", escape="\\"),
                )
            )
        rows = await session.scalars(
            select(CodeChunk).where(
                CodeChunk.project_id == project_id,
                CodeChunk.language.in_(list(languages)),
                CodeChunk.embedding.is_not(None),
                CodeChunk.embedding_status == "ready",
                CodeChunk.index_status == "ready",
                *((or_(*path_predicates),) if path_predicates else ()),
            )
        )
        scored: list[tuple[int, float]] = []
        for chunk in rows:
            if chunk.embedding is None:
                continue
            try:
                raw = chunk.embedding
                vector = json.loads(raw) if isinstance(raw, str) else raw
                if not isinstance(vector, list) or len(vector) == 0:
                    continue
                similarity = _cosine_similarity(query_vector, [float(v) for v in vector])
                scored.append((chunk.id, similarity))
            except (json.JSONDecodeError, TypeError, ValueError):
                continue
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return scored[:top_k]

    @staticmethod
    def _path_filter(target_paths: Sequence[str], params: dict[str, object]) -> str:
        normalized = tuple(
            dict.fromkeys(path.strip().replace("\\", "/").rstrip("/") for path in target_paths)
        )
        normalized = tuple(path for path in normalized if path)
        if not normalized:
            return ""

        clauses: list[str] = []
        for index, path in enumerate(normalized):
            exact_key = f"path_{index}"
            prefix_key = f"path_prefix_{index}"
            escaped_path = path.replace("%", "\\%").replace("_", "\\_")
            params[exact_key] = path
            params[prefix_key] = f"{escaped_path}/%"
            clauses.append(
                f"(relative_path = :{exact_key} OR relative_path LIKE :{prefix_key} ESCAPE '\\')"
            )
        return "AND (" + " OR ".join(clauses) + ")"
