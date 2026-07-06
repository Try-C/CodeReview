"""Supported language adapters and their default registry."""

import tree_sitter_java
import tree_sitter_python
from tree_sitter import Language, Parser

from app.core.config import Settings, get_settings
from app.languages.base import LanguageAdapter
from app.languages.java import JavaLanguageAdapter
from app.languages.python import PythonLanguageAdapter
from app.languages.registry import LanguageAdapterRegistry, UnsupportedLanguageError
from app.languages.schemas import ParsedChunk, ParseResult, SymbolRef


def create_default_registry(settings: Settings | None = None) -> LanguageAdapterRegistry:
    """Build the production registry while keeping parsers constructor-injected."""

    active_settings = settings or get_settings()
    chunk_options = {
        "max_chunk_lines": active_settings.chunk_max_lines,
        "overlap_lines": active_settings.chunk_overlap_lines,
    }
    registry = LanguageAdapterRegistry()
    registry.register(
        JavaLanguageAdapter(
            Parser(Language(tree_sitter_java.language())),
            **chunk_options,
        )
    )
    registry.register(
        PythonLanguageAdapter(
            Parser(Language(tree_sitter_python.language())),
            **chunk_options,
        )
    )
    return registry


__all__ = [
    "JavaLanguageAdapter",
    "LanguageAdapter",
    "LanguageAdapterRegistry",
    "ParseResult",
    "ParsedChunk",
    "PythonLanguageAdapter",
    "SymbolRef",
    "UnsupportedLanguageError",
    "create_default_registry",
]
