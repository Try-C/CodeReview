"""Language-neutral parser domain contracts."""

from dataclasses import dataclass, field
from typing import Any, Literal

RelationType = Literal["call", "import", "extend", "implement", "reference"]
ResolutionStatus = Literal["resolved", "unresolved", "external"]


@dataclass(frozen=True, slots=True)
class ParsedChunk:
    """One source-backed semantic unit emitted by a language adapter."""

    file_path: str
    language: str
    symbol_type: str
    symbol_name: str
    qualified_name: str = ""
    signature: str = ""
    parent_symbol: str | None = None
    start_line: int = 0
    end_line: int = 0
    content: str = ""
    imports: tuple[str, ...] = ()
    content_hash: str = ""
    chunk_fingerprint: str = ""
    neighbors: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    parser_name: str = "tree_sitter"
    parser_version: str = "1"
    parse_confidence: float = 1.0

    def __post_init__(self) -> None:
        if not self.file_path or not self.language:
            raise ValueError("Parsed chunks require a file path and language")
        if self.start_line < 1 or self.end_line < self.start_line:
            raise ValueError("Parsed chunk line ranges must be positive and ordered")
        if not self.content:
            raise ValueError("Parsed chunks require source content")
        if not 0 <= self.parse_confidence <= 1:
            raise ValueError("parse_confidence must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class SymbolRef:
    """A deliberately lightweight, confidence-scored symbol relationship."""

    source_symbol: str
    target_symbol: str
    source_file: str
    target_file: str | None = None
    relation_type: RelationType = "call"
    confidence: float = 0.5
    resolution_status: ResolutionStatus = "unresolved"

    def __post_init__(self) -> None:
        if not self.source_symbol or not self.target_symbol or not self.source_file:
            raise ValueError("Symbol references require source, target, and source file")
        if not 0 <= self.confidence <= 1:
            raise ValueError("confidence must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class ParseResult:
    """Complete parser outcome for one supported source file."""

    language: str
    file_path: str
    chunks: tuple[ParsedChunk, ...]
    symbol_refs: tuple[SymbolRef, ...] = ()
    errors: tuple[str, ...] = ()
    fallback_used: bool = False
    parse_strategy: Literal["tree_sitter", "line_window"] = "tree_sitter"
    parse_confidence: float = 1.0

    def __post_init__(self) -> None:
        if not self.language or not self.file_path:
            raise ValueError("Parse results require a language and file path")
        if not 0 <= self.parse_confidence <= 1:
            raise ValueError("parse_confidence must be between 0 and 1")
