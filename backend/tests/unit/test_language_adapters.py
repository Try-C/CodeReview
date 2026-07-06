"""Language-specific parsing and registry behavior."""

import pytest

from app.core.config import Settings
from app.languages import UnsupportedLanguageError, create_default_registry


def test_registry_resolves_only_registered_source_extensions() -> None:
    registry = create_default_registry()

    assert registry.languages == ("java", "python")
    assert registry.resolve("src/Main.JAVA", "class Main {}").language == "java"
    assert registry.resolve("src/main.PY", "value = 1").language == "python"
    with pytest.raises(UnsupportedLanguageError, match="Unsupported source language"):
        registry.resolve("src/main.go", "package main")


def test_python_adapter_extracts_nested_symbols_imports_and_inheritance() -> None:
    source = (
        "from framework import Base\n\n"
        "class Service(Base):\n"
        "    def review(self, value):\n"
        "        return helper(value)\n"
    )
    adapter = create_default_registry().resolve("service.py", source)

    result = adapter.parse("service.py", source)

    assert [(chunk.symbol_type, chunk.qualified_name) for chunk in result.chunks] == [
        ("class", "Service"),
        ("method", "Service.review"),
    ]
    method = result.chunks[1]
    assert method.parent_symbol == "Service"
    assert method.signature == "def review(self, value)"
    assert method.imports == ("framework",)
    assert {
        (reference.relation_type, reference.source_symbol, reference.target_symbol)
        for reference in result.symbol_refs
    } >= {
        ("import", "<module>", "framework"),
        ("extend", "Service", "Base"),
        ("call", "Service.review", "helper"),
    }


def test_java_adapter_extracts_methods_imports_and_type_relationships() -> None:
    source = (
        "package demo;\n"
        "import java.util.List;\n"
        "class Service extends Base implements Runnable {\n"
        "  public void run() { audit.check(); }\n"
        "}\n"
    )
    adapter = create_default_registry().resolve("Service.java", source)

    result = adapter.parse("Service.java", source)

    assert [(chunk.symbol_type, chunk.qualified_name) for chunk in result.chunks] == [
        ("class", "Service"),
        ("method", "Service.run"),
    ]
    assert result.chunks[1].signature == "public void run()"
    assert result.chunks[1].imports == ("java.util.List",)
    assert {
        (reference.relation_type, reference.source_symbol, reference.target_symbol)
        for reference in result.symbol_refs
    } >= {
        ("import", "<compilation_unit>", "java.util.List"),
        ("extend", "Service", "Base"),
        ("implement", "Service", "Runnable"),
        ("call", "Service.run", "audit.check"),
    }


def test_java_interface_extends_relations_are_retained() -> None:
    source = "interface Auditable extends Closeable, Serializable {}\n"
    adapter = create_default_registry().resolve("Auditable.java", source)

    result = adapter.parse("Auditable.java", source)

    assert {
        (reference.relation_type, reference.target_symbol) for reference in result.symbol_refs
    } == {("extend", "Closeable"), ("extend", "Serializable")}


def test_content_hash_is_reusable_but_fingerprint_includes_location() -> None:
    adapter = create_default_registry().resolve("one.py", "def same():\n    return 1\n")

    first = adapter.parse("one.py", "def same():\n    return 1\n").chunks[0]
    relocated = adapter.parse("nested/two.py", "def same():\n    return 1\n").chunks[0]

    assert first.content_hash == relocated.content_hash
    assert first.chunk_fingerprint != relocated.chunk_fingerprint


def test_oversized_symbol_is_split_with_configured_overlap() -> None:
    source = "def long_function():\n" + "".join(
        f"    value_{number} = {number}\n" for number in range(10)
    )
    settings = Settings(
        _env_file=None,
        chunk_ideal_min_lines=2,
        chunk_ideal_max_lines=4,
        chunk_max_lines=5,
        chunk_overlap_lines=1,
    )
    adapter = create_default_registry(settings).resolve("long.py", source)

    chunks = adapter.parse("long.py", source).chunks

    assert len(chunks) == 3
    assert all(chunk.end_line - chunk.start_line + 1 <= 5 for chunk in chunks)
    assert chunks[0].end_line == chunks[1].start_line
    assert len({chunk.chunk_fingerprint for chunk in chunks}) == len(chunks)
    assert [chunk.metadata["split_part"] for chunk in chunks] == [1, 2, 3]
