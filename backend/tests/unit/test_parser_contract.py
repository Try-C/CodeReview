"""Shared contract tests that every P0 language adapter must satisfy."""

from collections.abc import Callable

import pytest
import tree_sitter_java
import tree_sitter_python
from tree_sitter import Language, Parser, Tree

from app.languages import JavaLanguageAdapter, PythonLanguageAdapter
from app.languages.base import LanguageAdapter

AdapterFactory = Callable[[], LanguageAdapter]
CHUNK_OPTIONS = {"max_chunk_lines": 200, "overlap_lines": 15}


def python_adapter() -> LanguageAdapter:
    return PythonLanguageAdapter(
        Parser(Language(tree_sitter_python.language())),
        **CHUNK_OPTIONS,
    )


def java_adapter() -> LanguageAdapter:
    return JavaLanguageAdapter(
        Parser(Language(tree_sitter_java.language())),
        **CHUNK_OPTIONS,
    )


@pytest.fixture(
    params=[
        (
            python_adapter,
            "src/service.py",
            "import os\n\ndef review(value):\n    return sanitize(value)\n",
            "review",
            "sanitize",
        ),
        (
            java_adapter,
            "src/Service.java",
            (
                "import java.util.List;\n"
                "class Service {\n"
                "  String review(String value) { return sanitize(value); }\n"
                "}\n"
            ),
            "Service.review",
            "sanitize",
        ),
    ],
    ids=["python", "java"],
)
def contract_case(
    request: pytest.FixtureRequest,
) -> tuple[LanguageAdapter, str, str, str, str]:
    factory, file_path, content, source_symbol, target_symbol = request.param
    return factory(), file_path, content, source_symbol, target_symbol


def test_adapter_emits_source_backed_chunks_with_stable_identity(
    contract_case: tuple[LanguageAdapter, str, str, str, str],
) -> None:
    adapter, file_path, content, _, _ = contract_case

    first = adapter.parse(file_path, content)
    second = adapter.parse(file_path, content)

    assert first.language == adapter.language
    assert first.file_path == file_path
    assert first.parse_strategy == "tree_sitter"
    assert first.parse_confidence == 1
    assert not first.fallback_used
    assert first.chunks
    assert [chunk.chunk_fingerprint for chunk in first.chunks] == [
        chunk.chunk_fingerprint for chunk in second.chunks
    ]
    for chunk in first.chunks:
        assert chunk.file_path == file_path
        assert chunk.language == adapter.language
        assert chunk.start_line >= 1
        assert chunk.end_line >= chunk.start_line
        assert chunk.content in content
        assert len(chunk.content_hash) == 64
        assert len(chunk.chunk_fingerprint) == 64
        assert chunk.parser_name == "tree_sitter"


def test_adapter_emits_confidence_scored_calls(
    contract_case: tuple[LanguageAdapter, str, str, str, str],
) -> None:
    adapter, file_path, content, source_symbol, target_symbol = contract_case

    result = adapter.parse(file_path, content)

    call = next(
        reference
        for reference in result.symbol_refs
        if reference.relation_type == "call" and reference.target_symbol == target_symbol
    )
    assert call.source_symbol == source_symbol
    assert call.source_file == file_path
    assert 0 < call.confidence <= 1
    assert call.resolution_status == "unresolved"


def test_adapter_falls_back_for_syntax_errors(
    contract_case: tuple[LanguageAdapter, str, str, str, str],
) -> None:
    adapter, file_path, _, _, _ = contract_case
    invalid_source = (
        "def broken(:\n" if adapter.language == "python" else "class Broken { void x( }"
    )

    result = adapter.parse(file_path, invalid_source)

    assert result.fallback_used
    assert result.parse_strategy == "line_window"
    assert result.parse_confidence < 1
    assert result.errors == ("TREE_SITTER_SYNTAX_ERROR",)
    assert result.chunks[0].parser_name == "line_window"
    assert result.chunks[0].metadata["fallback_reason"] == "TREE_SITTER_SYNTAX_ERROR"


def test_adapter_falls_back_when_injected_parser_fails() -> None:
    class FailingParser:
        def parse(self, source: bytes, /) -> Tree:
            del source
            raise RuntimeError("parser unavailable")

    adapter = PythonLanguageAdapter(FailingParser(), **CHUNK_OPTIONS)

    result = adapter.parse("service.py", "value = 1\n")

    assert result.fallback_used
    assert result.errors == ("TREE_SITTER_FAILED: RuntimeError",)
