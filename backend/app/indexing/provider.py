"""Embedding provider boundary and Alibaba Cloud Model Studio adapter."""

from collections.abc import Sequence
from typing import Literal, Protocol

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

EmbeddingTextType = Literal["document", "query"]


class EmbeddingProviderError(RuntimeError):
    """A sanitized provider failure safe to persist as a degradation reason."""


class _EmbeddingItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    text_index: int = Field(ge=0)
    embedding: list[float]


class _EmbeddingOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    embeddings: list[_EmbeddingItem]


class _EmbeddingResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    output: _EmbeddingOutput


class EmbeddingProvider(Protocol):
    """Provider-neutral async embedding interface."""

    model: str
    dimension: int

    async def embed(
        self,
        texts: Sequence[str],
        *,
        text_type: EmbeddingTextType,
    ) -> list[list[float]]:
        """Return one dense vector per input, preserving input order."""


class UnavailableEmbeddingProvider:
    """Fail predictably so indexing and retrieval can degrade to keyword-only."""

    model = "unavailable"
    dimension = 1024

    async def embed(
        self,
        texts: Sequence[str],
        *,
        text_type: EmbeddingTextType,
    ) -> list[list[float]]:
        del texts, text_type
        raise EmbeddingProviderError("EMBEDDING_PROVIDER_UNAVAILABLE")


class DashScopeEmbeddingProvider:
    """Call the native DashScope endpoint with an injected HTTP client."""

    _ENDPOINT = "/services/embeddings/text-embedding/text-embedding"

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        api_key: str,
        model: str = "text-embedding-v4",
        dimension: int = 1024,
        max_batch_size: int = 10,
    ) -> None:
        if not api_key:
            raise ValueError("DashScope API key is required")
        if dimension != 1024:
            raise ValueError("P0 embedding dimension must be 1024")
        if not 1 <= max_batch_size <= 10:
            raise ValueError("DashScope batch size must be between 1 and 10")
        self._client = client
        self._api_key = api_key
        self.model = model
        self.dimension = dimension
        self.max_batch_size = max_batch_size

    async def embed(
        self,
        texts: Sequence[str],
        *,
        text_type: EmbeddingTextType,
    ) -> list[list[float]]:
        if not texts:
            return []
        if len(texts) > self.max_batch_size:
            raise ValueError(f"Embedding batch exceeds {self.max_batch_size} inputs")
        try:
            response = await self._client.post(
                self._ENDPOINT,
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={
                    "model": self.model,
                    "input": {"texts": list(texts)},
                    "parameters": {
                        "dimension": self.dimension,
                        "output_type": "dense",
                        "text_type": text_type,
                    },
                },
            )
            response.raise_for_status()
            parsed = _EmbeddingResponse.model_validate(response.json())
        except (httpx.HTTPError, ValueError, ValidationError) as error:
            raise EmbeddingProviderError(
                f"EMBEDDING_PROVIDER_FAILED:{type(error).__name__}"
            ) from error

        items = sorted(parsed.output.embeddings, key=lambda item: item.text_index)
        if [item.text_index for item in items] != list(range(len(texts))):
            raise EmbeddingProviderError("EMBEDDING_PROVIDER_INVALID_INDEXES")
        vectors = [item.embedding for item in items]
        if any(len(vector) != self.dimension for vector in vectors):
            raise EmbeddingProviderError("EMBEDDING_PROVIDER_INVALID_DIMENSION")
        return vectors
