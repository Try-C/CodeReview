"""Retry-safe incremental code indexing."""

from collections.abc import Sequence
from dataclasses import dataclass
from hashlib import sha256
from typing import Protocol

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.indexing.provider import EmbeddingProvider, EmbeddingProviderError
from app.indexing.text import build_search_text
from app.languages.schemas import ParsedChunk, ParseResult
from app.models.index import CodeChunk, CodeRelation, CodeSymbol
from app.models.project import ProjectFile


class TokenCounter(Protocol):
    """Count model input tokens without coupling indexing to one tokenizer."""

    def count(self, text: str) -> int:
        """Return the token count for one input."""


class ConservativeTokenCounter:
    """Use UTF-8 bytes as a safe upper bound when no tokenizer is installed."""

    def count(self, text: str) -> int:
        return len(text.encode("utf-8"))


@dataclass(frozen=True, slots=True)
class IndexBuildResult:
    """Observable outcome for one atomic file update."""

    indexed_chunks: int
    embedded_chunks: int
    reused_embeddings: int
    keyword_only_chunks: int
    reused_file: bool = False


@dataclass(slots=True)
class _PreparedChunk:
    parsed: ParsedChunk
    search_text: str
    embedding: list[float] | None = None
    embedding_status: str = "pending"
    embedding_error: str | None = None
    reused_embedding: bool = False


class IndexingService:
    """Embed outside a transaction, then replace one file atomically."""

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        provider: EmbeddingProvider,
        *,
        embedding_version: int = 1,
        batch_size: int = 10,
        max_input_tokens: int = 8192,
        token_counter: TokenCounter | None = None,
    ) -> None:
        if provider.dimension != 1024:
            raise ValueError("P0 embeddings must contain 1024 dimensions")
        if not 1 <= batch_size <= 10:
            raise ValueError("Embedding batch size must be between 1 and 10")
        self._sessions = sessions
        self._provider = provider
        self._embedding_version = embedding_version
        self._batch_size = batch_size
        self._max_input_tokens = max_input_tokens
        self._token_counter = token_counter or ConservativeTokenCounter()

    async def index_file(
        self,
        *,
        project_id: int,
        file_id: int,
        file_hash: str,
        parse_result: ParseResult,
    ) -> IndexBuildResult:
        """Index one parser result with content-based embedding reuse."""
        if not file_hash:
            raise ValueError("file_hash is required")
        if any(chunk.file_path != parse_result.file_path for chunk in parse_result.chunks):
            raise ValueError("All chunks must belong to the parsed file")

        existing, reusable = await self._load_existing(
            project_id=project_id,
            file_id=file_id,
            content_hashes={chunk.content_hash for chunk in parse_result.chunks},
        )
        if self._is_current(existing, file_hash, parse_result.chunks):
            embedded = sum(chunk.embedding_status == "ready" for chunk in existing)
            return IndexBuildResult(
                indexed_chunks=len(existing),
                embedded_chunks=embedded,
                reused_embeddings=embedded,
                keyword_only_chunks=len(existing) - embedded,
                reused_file=True,
            )

        prepared = [
            _PreparedChunk(parsed=chunk, search_text=build_search_text(chunk))
            for chunk in parse_result.chunks
        ]
        for item in prepared:
            previous = reusable.get(item.parsed.content_hash)
            if previous is not None:
                item.embedding = previous
                item.embedding_status = "ready"
                item.reused_embedding = True
            elif self._token_counter.count(item.search_text) > self._max_input_tokens:
                item.embedding_status = "keyword_only"
                item.embedding_error = "EMBEDDING_INPUT_TOKEN_LIMIT"

        pending = [item for item in prepared if item.embedding_status == "pending"]
        for offset in range(0, len(pending), self._batch_size):
            batch = pending[offset : offset + self._batch_size]
            try:
                vectors = await self._provider.embed(
                    [item.search_text for item in batch],
                    text_type="document",
                )
                if len(vectors) != len(batch):
                    raise EmbeddingProviderError("EMBEDDING_PROVIDER_INVALID_COUNT")
                for item, vector in zip(batch, vectors, strict=True):
                    if len(vector) != 1024:
                        raise EmbeddingProviderError("EMBEDDING_PROVIDER_INVALID_DIMENSION")
                    item.embedding = vector
                    item.embedding_status = "ready"
            except EmbeddingProviderError as error:
                reason = str(error)[:128]
                for item in batch:
                    item.embedding_status = "keyword_only"
                    item.embedding_error = reason

        await self._replace_file(
            project_id=project_id,
            file_id=file_id,
            file_hash=file_hash,
            parse_result=parse_result,
            prepared=prepared,
        )
        return IndexBuildResult(
            indexed_chunks=len(prepared),
            embedded_chunks=sum(item.embedding_status == "ready" for item in prepared),
            reused_embeddings=sum(item.reused_embedding for item in prepared),
            keyword_only_chunks=sum(item.embedding_status == "keyword_only" for item in prepared),
        )

    async def _load_existing(
        self,
        *,
        project_id: int,
        file_id: int,
        content_hashes: set[str],
    ) -> tuple[list[CodeChunk], dict[str, list[float]]]:
        async with self._sessions() as session:
            existing = list(
                await session.scalars(
                    select(CodeChunk)
                    .where(CodeChunk.project_id == project_id, CodeChunk.file_id == file_id)
                    .order_by(CodeChunk.id)
                )
            )
            reusable: dict[str, list[float]] = {}
            if content_hashes:
                rows = await session.execute(
                    select(CodeChunk.content_hash, CodeChunk.embedding).where(
                        CodeChunk.project_id == project_id,
                        CodeChunk.content_hash.in_(content_hashes),
                        CodeChunk.embedding_model == self._provider.model,
                        CodeChunk.embedding_version == self._embedding_version,
                        CodeChunk.embedding_status == "ready",
                        CodeChunk.embedding.is_not(None),
                    )
                )
                for content_hash, embedding in rows:
                    reusable.setdefault(content_hash, embedding)
            return existing, reusable

    def _is_current(
        self,
        existing: Sequence[CodeChunk],
        file_hash: str,
        parsed: Sequence[ParsedChunk],
    ) -> bool:
        if len(existing) != len(parsed):
            return False
        expected = {chunk.chunk_fingerprint: chunk for chunk in parsed}
        return all(
            chunk.file_hash == file_hash
            and chunk.chunk_fingerprint in expected
            and chunk.parser_name == expected[chunk.chunk_fingerprint].parser_name
            and chunk.parser_version == expected[chunk.chunk_fingerprint].parser_version
            and chunk.embedding_model == self._provider.model
            and chunk.embedding_version == self._embedding_version
            and chunk.index_status == "ready"
            and chunk.embedding_status in {"ready", "keyword_only"}
            for chunk in existing
        )

    async def _replace_file(
        self,
        *,
        project_id: int,
        file_id: int,
        file_hash: str,
        parse_result: ParseResult,
        prepared: Sequence[_PreparedChunk],
    ) -> None:
        async with self._sessions.begin() as session:
            project_file = await session.get(ProjectFile, file_id)
            if project_file is None or project_file.project_id != project_id:
                raise ValueError("Project file does not belong to project")

            old_symbol_ids = select(CodeSymbol.id).where(CodeSymbol.file_id == file_id)
            await session.execute(
                delete(CodeRelation).where(CodeRelation.source_symbol_id.in_(old_symbol_ids))
            )
            await session.execute(
                update(CodeRelation)
                .where(CodeRelation.target_symbol_id.in_(old_symbol_ids))
                .values(target_symbol_id=None, resolution_status="unresolved")
            )
            await session.execute(delete(CodeSymbol).where(CodeSymbol.file_id == file_id))
            await session.execute(delete(CodeChunk).where(CodeChunk.file_id == file_id))

            persisted_chunks: dict[str, CodeChunk] = {}
            for item in prepared:
                chunk = item.parsed
                record = CodeChunk(
                    project_id=project_id,
                    file_id=file_id,
                    relative_path=chunk.file_path,
                    file_hash=file_hash,
                    content_hash=chunk.content_hash,
                    chunk_fingerprint=chunk.chunk_fingerprint,
                    language=chunk.language,
                    symbol_type=chunk.symbol_type or None,
                    symbol_name=chunk.symbol_name or None,
                    qualified_name=chunk.qualified_name or None,
                    parent_symbol=chunk.parent_symbol,
                    start_line=chunk.start_line,
                    end_line=chunk.end_line,
                    content=chunk.content,
                    neighbors=chunk.neighbors,
                    metadata_=chunk.metadata,
                    parser_name=chunk.parser_name,
                    parser_version=chunk.parser_version,
                    parse_confidence=chunk.parse_confidence,
                    embedding_model=self._provider.model,
                    embedding_version=self._embedding_version,
                    embedding=item.embedding,
                    embedding_status=item.embedding_status,
                    embedding_error=item.embedding_error,
                    index_status="ready",
                    search_text=item.search_text,
                    search_vector=(
                        item.search_text if session.bind.dialect.name == "sqlite" else None
                    ),
                )
                session.add(record)
                persisted_chunks[chunk.chunk_fingerprint] = record
            await session.flush()

            symbols = self._create_symbols(
                project_id=project_id,
                file_id=file_id,
                chunks=parse_result.chunks,
                persisted=persisted_chunks,
            )
            session.add_all(symbols)
            await session.flush()
            session.add_all(self._create_relations(project_id, parse_result, symbols))

    @staticmethod
    def _create_symbols(
        *,
        project_id: int,
        file_id: int,
        chunks: Sequence[ParsedChunk],
        persisted: dict[str, CodeChunk],
    ) -> list[CodeSymbol]:
        symbols: list[CodeSymbol] = []
        for chunk in chunks:
            if not chunk.symbol_name:
                continue
            identity = (
                f"{chunk.file_path}\0{chunk.qualified_name or chunk.symbol_name}"
                f"\0{chunk.start_line}\0{chunk.end_line}"
            )
            symbols.append(
                CodeSymbol(
                    project_id=project_id,
                    file_id=file_id,
                    chunk_id=persisted[chunk.chunk_fingerprint].id,
                    symbol_hash=sha256(identity.encode()).hexdigest(),
                    symbol_name=chunk.symbol_name,
                    qualified_name=chunk.qualified_name or None,
                    symbol_type=chunk.symbol_type,
                    relative_path=chunk.file_path,
                    start_line=chunk.start_line,
                    end_line=chunk.end_line,
                    signature=chunk.signature or None,
                    metadata_={},
                )
            )
        return symbols

    @staticmethod
    def _create_relations(
        project_id: int,
        parse_result: ParseResult,
        symbols: Sequence[CodeSymbol],
    ) -> list[CodeRelation]:
        by_name: dict[str, CodeSymbol] = {}
        for symbol in symbols:
            by_name[symbol.symbol_name] = symbol
            if symbol.qualified_name:
                by_name[symbol.qualified_name] = symbol

        relations: list[CodeRelation] = []
        seen: set[tuple[int, str, str]] = set()
        for reference in parse_result.symbol_refs:
            source = by_name.get(reference.source_symbol)
            if source is None:
                continue
            key = (source.id, reference.target_symbol, reference.relation_type)
            if key in seen:
                continue
            seen.add(key)
            target = by_name.get(reference.target_symbol)
            resolution = "resolved" if target is not None else reference.resolution_status
            relations.append(
                CodeRelation(
                    project_id=project_id,
                    source_symbol_id=source.id,
                    target_symbol_id=target.id if target is not None else None,
                    target_name=reference.target_symbol,
                    relation_type=reference.relation_type,
                    confidence=reference.confidence,
                    resolution_status=resolution,
                    metadata_={},
                )
            )
        return relations
