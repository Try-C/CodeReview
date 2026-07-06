"""Deterministic full-text input construction."""

import re

from app.languages.schemas import ParsedChunk

_ACRONYM_BOUNDARY = re.compile(r"([A-Z]+)([A-Z][a-z])")
_CAMEL_BOUNDARY = re.compile(r"([a-z0-9])([A-Z])")
_SEPARATORS = re.compile(r"[^A-Za-z0-9]+")


def split_identifier(value: str) -> str:
    """Split camelCase, acronym, snake_case, and path separators for FTS."""
    acronym_split = _ACRONYM_BOUNDARY.sub(r"\1 \2", value)
    camel_split = _CAMEL_BOUNDARY.sub(r"\1 \2", acronym_split)
    return " ".join(_SEPARATORS.sub(" ", camel_split).lower().split())


def build_search_text(chunk: ParsedChunk) -> str:
    """Keep original identifiers beside normalized tokens and source."""
    identifiers = (
        chunk.file_path,
        chunk.symbol_name,
        chunk.qualified_name,
        *chunk.imports,
    )
    original = [identifier for identifier in identifiers if identifier]
    normalized = [split_identifier(identifier) for identifier in original]
    return "\n".join((*original, *normalized, chunk.content))
