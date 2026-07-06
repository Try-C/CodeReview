"""Code indexing, embedding, and incremental persistence."""

from app.indexing.database import HnswSearchOptions, PgVectorStartupCheck, PgVectorValidator
from app.indexing.metrics import recall_at_k
from app.indexing.provider import (
    DashScopeEmbeddingProvider,
    EmbeddingProvider,
    EmbeddingProviderError,
    UnavailableEmbeddingProvider,
)
from app.indexing.service import IndexBuildResult, IndexingService
from app.indexing.text import build_search_text, split_identifier

__all__ = [
    "DashScopeEmbeddingProvider",
    "EmbeddingProvider",
    "EmbeddingProviderError",
    "HnswSearchOptions",
    "IndexBuildResult",
    "IndexingService",
    "PgVectorStartupCheck",
    "PgVectorValidator",
    "UnavailableEmbeddingProvider",
    "build_search_text",
    "recall_at_k",
    "split_identifier",
]
