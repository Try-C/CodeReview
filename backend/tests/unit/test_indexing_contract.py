"""Provider, text-index, HNSW, and metric contract tests."""

import asyncio
from typing import Any

import httpx
import pytest

from app.indexing import (
    DashScopeEmbeddingProvider,
    EmbeddingProviderError,
    HnswSearchOptions,
    PgVectorValidator,
    build_search_text,
    recall_at_k,
    split_identifier,
)
from app.languages import ParsedChunk


def test_identifier_splitting_and_search_text_preserve_both_forms() -> None:
    chunk = ParsedChunk(
        file_path="src/user_repository.py",
        language="python",
        symbol_type="function",
        symbol_name="findUserByName",
        qualified_name="UserRepository.findUserByName",
        start_line=1,
        end_line=2,
        content="def findUserByName():\n    pass",
        imports=("HTTPServer",),
    )

    search_text = build_search_text(chunk)

    assert split_identifier("findUserByName") == "find user by name"
    assert split_identifier("HTTPServer") == "http server"
    assert split_identifier("user_repository") == "user repository"
    assert "findUserByName" in search_text
    assert "find user by name" in search_text


def test_dashscope_provider_sends_native_dense_document_request() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["authorization"] = request.headers["Authorization"]
        captured["body"] = request.read().decode()
        return httpx.Response(
            200,
            json={
                "output": {
                    "embeddings": [
                        {"text_index": 1, "embedding": [2.0] * 1024},
                        {"text_index": 0, "embedding": [1.0] * 1024},
                    ]
                }
            },
        )

    async def scenario() -> list[list[float]]:
        async with httpx.AsyncClient(
            base_url="https://dashscope.example/api/v1",
            transport=httpx.MockTransport(handler),
        ) as client:
            provider = DashScopeEmbeddingProvider(client, api_key="test-only")
            return await provider.embed(["first", "second"], text_type="document")

    vectors = asyncio.run(scenario())

    assert captured["authorization"] == "Bearer test-only"
    assert '"text_type":"document"' in captured["body"]
    assert '"dimension":1024' in captured["body"]
    assert vectors[0][0] == 1.0
    assert vectors[1][0] == 2.0


def test_dashscope_provider_sanitizes_http_failures() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(401, json={"message": "secret leaked by upstream"})

    async def scenario() -> None:
        async with httpx.AsyncClient(
            base_url="https://dashscope.example/api/v1",
            transport=httpx.MockTransport(handler),
        ) as client:
            provider = DashScopeEmbeddingProvider(client, api_key="actual-secret")
            with pytest.raises(EmbeddingProviderError) as caught:
                await provider.embed(["code"], text_type="query")
            assert "actual-secret" not in str(caught.value)
            assert "secret leaked" not in str(caught.value)

    asyncio.run(scenario())


def test_hnsw_options_are_transaction_local() -> None:
    class MockBind:
        class dialect:
            name = "postgresql"

    class RecordingSession:
        def __init__(self) -> None:
            self.statements: list[str] = []
            self.bind = MockBind()

        async def execute(self, statement: Any) -> None:
            self.statements.append(str(statement))

    async def scenario() -> list[str]:
        session = RecordingSession()
        await HnswSearchOptions(ef_search=100, iterative_scan="strict_order").apply(
            session  # type: ignore[arg-type]
        )
        return session.statements

    assert asyncio.run(scenario()) == [
        "SET LOCAL hnsw.ef_search = 100",
        "SET LOCAL hnsw.iterative_scan = strict_order",
    ]


def test_pgvector_version_and_recall_validation() -> None:
    class ScalarSession:
        async def scalar(self, statement: Any) -> str:
            del statement
            return "0.8.1"

    asyncio.run(
        PgVectorValidator(dimension=1024, minimum_version="0.8.0").validate(
            ScalarSession()  # type: ignore[arg-type]
        )
    )
    assert recall_at_k({1, 2}, [3, 2, 4], 2) == 0.5
    assert recall_at_k(set(), [], 10) == 1
    with pytest.raises(ValueError, match="positive"):
        recall_at_k({1}, [1], 0)
