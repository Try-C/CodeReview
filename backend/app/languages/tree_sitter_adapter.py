"""Shared, non-executing Tree-sitter parsing mechanics."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from hashlib import sha256
from pathlib import PurePosixPath
from typing import Protocol

from tree_sitter import Node, Tree

from app.languages.base import LanguageAdapter
from app.languages.schemas import ParsedChunk, ParseResult, SymbolRef

FALLBACK_CONFIDENCE = 0.35


class TreeSitterParser(Protocol):
    """Minimal injectable Tree-sitter parser surface."""

    def parse(self, source: bytes, /) -> Tree: ...


@dataclass(frozen=True, slots=True)
class Definition:
    node: Node
    symbol_type: str
    name: str
    qualified_name: str
    parent_symbol: str | None


class TreeSitterLanguageAdapter(LanguageAdapter):
    """Base implementation for source-backed semantic chunks and fallback."""

    definition_types: frozenset[str]
    parser_version = "1"

    def __init__(
        self,
        parser: TreeSitterParser,
        *,
        max_chunk_lines: int,
        overlap_lines: int,
    ) -> None:
        if max_chunk_lines < 1 or not 0 <= overlap_lines < max_chunk_lines:
            raise ValueError("Chunk limits require max >= 1 and 0 <= overlap < max")
        self._parser = parser
        self._max_chunk_lines = max_chunk_lines
        self._overlap_lines = overlap_lines

    def detect(self, file_path: str, content: str) -> bool:
        del content
        return PurePosixPath(file_path).suffix.casefold() in self.extensions

    def parse(self, file_path: str, content: str) -> ParseResult:
        source = content.encode("utf-8")
        try:
            tree = self._parser.parse(source)
        except Exception as exc:
            return self._fallback(file_path, content, f"TREE_SITTER_FAILED: {type(exc).__name__}")
        if tree.root_node.has_error:
            return self._fallback(file_path, content, "TREE_SITTER_SYNTAX_ERROR")

        imports = self._imports(tree.root_node, source)
        definitions = self._definitions(tree.root_node, source)
        chunks = tuple(
            chunk
            for definition in definitions
            for chunk in self._chunks(file_path, source, definition, imports)
        )
        if not chunks and content.strip():
            chunks = (self._file_chunk(file_path, content, imports),)
        references = self._references(file_path, tree.root_node, source, definitions, imports)
        return ParseResult(
            language=self.language,
            file_path=file_path,
            chunks=chunks,
            symbol_refs=references,
        )

    def _definitions(self, root: Node, source: bytes) -> tuple[Definition, ...]:
        definitions: list[Definition] = []
        for node in walk(root):
            if node.type not in self.definition_types:
                continue
            name_node = node.child_by_field_name("name")
            if name_node is None:
                continue
            name = node_text(name_node, source)
            parents = [definition for definition in definitions if contains(definition.node, node)]
            parent = min(
                parents, key=lambda item: item.node.end_byte - item.node.start_byte, default=None
            )
            parent_name = parent.qualified_name if parent else None
            qualified_name = f"{parent_name}.{name}" if parent_name else name
            definitions.append(
                Definition(
                    node=node,
                    symbol_type=self._symbol_type(node, parent),
                    name=name,
                    qualified_name=qualified_name,
                    parent_symbol=parent_name,
                )
            )
        return tuple(definitions)

    def _chunks(
        self,
        file_path: str,
        source: bytes,
        definition: Definition,
        imports: tuple[str, ...],
    ) -> tuple[ParsedChunk, ...]:
        content = node_text(definition.node, source)
        signature = self._signature(definition.node, source)
        start_line = definition.node.start_point.row + 1
        end_line = definition.node.end_point.row + 1
        if end_line - start_line + 1 <= self._max_chunk_lines:
            return (
                self._chunk(
                    file_path,
                    definition,
                    imports,
                    signature,
                    content,
                    start_line,
                    end_line,
                ),
            )
        lines = content.splitlines(keepends=True)
        step = self._max_chunk_lines - self._overlap_lines
        chunks: list[ParsedChunk] = []
        for offset in range(0, len(lines), step):
            selected = lines[offset : offset + self._max_chunk_lines]
            part_start = start_line + offset
            part_end = part_start + len(selected) - 1
            chunks.append(
                self._chunk(
                    file_path,
                    definition,
                    imports,
                    signature,
                    "".join(selected),
                    part_start,
                    part_end,
                    part_number=len(chunks) + 1,
                )
            )
            if part_end == end_line:
                break
        return tuple(chunks)

    def _chunk(
        self,
        file_path: str,
        definition: Definition,
        imports: tuple[str, ...],
        signature: str,
        content: str,
        start_line: int,
        end_line: int,
        *,
        part_number: int | None = None,
    ) -> ParsedChunk:
        content_hash = hash_content(content)
        identity = definition.qualified_name or definition.name
        fingerprint = hash_fingerprint(file_path, identity, start_line, end_line, content_hash)
        metadata: dict[str, object] = {"tree_sitter_node_type": definition.node.type}
        if part_number is not None:
            metadata.update({"split_part": part_number, "split_symbol": identity})
        return ParsedChunk(
            file_path=file_path,
            language=self.language,
            symbol_type=definition.symbol_type,
            symbol_name=definition.name,
            qualified_name=definition.qualified_name,
            signature=signature,
            parent_symbol=definition.parent_symbol,
            start_line=start_line,
            end_line=end_line,
            content=content,
            imports=imports,
            content_hash=content_hash,
            chunk_fingerprint=fingerprint,
            metadata=metadata,
            parser_version=self.parser_version,
        )

    def _file_chunk(self, file_path: str, content: str, imports: tuple[str, ...]) -> ParsedChunk:
        line_count = max(len(content.splitlines()), 1)
        content_hash = hash_content(content)
        return ParsedChunk(
            file_path=file_path,
            language=self.language,
            symbol_type="module",
            symbol_name=PurePosixPath(file_path).stem,
            start_line=1,
            end_line=line_count,
            content=content,
            imports=imports,
            content_hash=content_hash,
            chunk_fingerprint=hash_fingerprint(file_path, "<module>", 1, line_count, content_hash),
        )

    def _fallback(self, file_path: str, content: str, error: str) -> ParseResult:
        lines = content.splitlines(keepends=True)
        if not lines:
            return ParseResult(
                language=self.language,
                file_path=file_path,
                chunks=(),
                errors=(error, "FALLBACK_EMPTY_SOURCE"),
                fallback_used=True,
                parse_strategy="line_window",
                parse_confidence=FALLBACK_CONFIDENCE,
            )
        chunks: list[ParsedChunk] = []
        step = self._max_chunk_lines - self._overlap_lines
        for start_index in range(0, len(lines), step):
            selected = lines[start_index : start_index + self._max_chunk_lines]
            if not selected:
                break
            start_line = start_index + 1
            end_line = start_index + len(selected)
            chunk_content = "".join(selected)
            content_hash = hash_content(chunk_content)
            identity = f"<fallback:{start_line}>"
            chunks.append(
                ParsedChunk(
                    file_path=file_path,
                    language=self.language,
                    symbol_type="line_window",
                    symbol_name=identity,
                    start_line=start_line,
                    end_line=end_line,
                    content=chunk_content,
                    content_hash=content_hash,
                    chunk_fingerprint=hash_fingerprint(
                        file_path, identity, start_line, end_line, content_hash
                    ),
                    parser_name="line_window",
                    parse_confidence=FALLBACK_CONFIDENCE,
                    metadata={"fallback_reason": error},
                )
            )
            if end_line == len(lines):
                break
        return ParseResult(
            language=self.language,
            file_path=file_path,
            chunks=tuple(chunks),
            errors=(error,),
            fallback_used=True,
            parse_strategy="line_window",
            parse_confidence=FALLBACK_CONFIDENCE,
        )

    def _symbol_type(self, node: Node, parent: Definition | None) -> str:
        raise NotImplementedError

    def _signature(self, node: Node, source: bytes) -> str:
        raise NotImplementedError

    def _imports(self, root: Node, source: bytes) -> tuple[str, ...]:
        raise NotImplementedError

    def _references(
        self,
        file_path: str,
        root: Node,
        source: bytes,
        definitions: tuple[Definition, ...],
        imports: tuple[str, ...],
    ) -> tuple[SymbolRef, ...]:
        raise NotImplementedError


def walk(node: Node) -> Iterator[Node]:
    yield node
    for child in node.children:
        yield from walk(child)


def node_text(node: Node, source: bytes) -> str:
    return source[node.start_byte : node.end_byte].decode("utf-8")


def contains(outer: Node, inner: Node) -> bool:
    return (
        outer.start_byte <= inner.start_byte and outer.end_byte >= inner.end_byte and outer != inner
    )


def owning_definition(node: Node, definitions: tuple[Definition, ...]) -> Definition | None:
    owners = [definition for definition in definitions if contains(definition.node, node)]
    return min(owners, key=lambda item: item.node.end_byte - item.node.start_byte, default=None)


def normalize_content(content: str) -> str:
    return "\n".join(line.rstrip() for line in content.replace("\r\n", "\n").split("\n")).strip()


def hash_content(content: str) -> str:
    return sha256(normalize_content(content).encode("utf-8")).hexdigest()


def hash_fingerprint(
    file_path: str,
    symbol_identity: str,
    start_line: int,
    end_line: int,
    content_hash: str,
) -> str:
    identity = "\0".join((file_path, symbol_identity, str(start_line), str(end_line), content_hash))
    return sha256(identity.encode("utf-8")).hexdigest()
