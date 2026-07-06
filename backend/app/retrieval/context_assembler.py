"""Dynamic context assembly: enrich retrieved chunks with symbols and relations."""

from collections.abc import Sequence
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.index import CodeRelation, CodeSymbol
from app.retrieval.hybrid_retriever import ScoredChunk


@dataclass(frozen=True, slots=True)
class AssembledContext:
    """One chunk enriched with its symbols, relations, and neighbour metadata."""

    chunk_id: int
    language: str
    relative_path: str
    start_line: int
    end_line: int
    symbol_name: str | None
    symbol_type: str | None
    qualified_name: str | None
    code: str
    neighbors: dict[str, object] = field(default_factory=dict)
    symbols: tuple[CodeSymbol, ...] = ()
    relations: tuple[CodeRelation, ...] = ()
    target_symbols: dict[int, CodeSymbol] = field(default_factory=dict)
    rrf_score: float = 0.0

    @property
    def estimated_tokens(self) -> int:
        """Upper-bound UTF-8 byte estimate as a proxy for token count."""
        return len(self.code.encode("utf-8")) + len(self.format_for_llm().encode("utf-8")) // 2

    def format_for_llm(self) -> str:
        """Produce a compact textual representation suitable for an LLM context window."""
        header = f"[{self.chunk_id}] {self.relative_path}:{self.start_line}-{self.end_line}"
        if self.symbol_name:
            kind = self.symbol_type or "symbol"
            name = self.qualified_name or self.symbol_name
            header += f" {kind} {name}"
        parts = [header]

        if self.neighbors:
            neighbors_brief = ", ".join(f"{key}={value}" for key, value in self.neighbors.items())
            parts.append(f"neighbors: {neighbors_brief}")

        parts.append("```" + (self.language or ""))
        parts.append(self.code.rstrip())
        parts.append("```")

        if self.symbols:
            parts.append("symbols:")
            for sym in self.symbols:
                loc = f"{sym.relative_path}:{sym.start_line}-{sym.end_line}"
                parts.append(f"  {sym.symbol_type} {sym.symbol_name} ({loc})")

        if self.relations:
            parts.append("references:")
            for rel in self.relations:
                confidence_info = f"confidence={rel.confidence:.2f}, {rel.resolution_status}"
                if rel.target_symbol_id is not None and rel.target_symbol_id in self.target_symbols:
                    target = self.target_symbols[rel.target_symbol_id]
                    confidence_info += f", target={target.qualified_name or target.symbol_name}"
                    if target.relative_path and target.relative_path != self.relative_path:
                        confidence_info += f", external_file={target.relative_path}"
                parts.append(f"  {rel.relation_type} -> {rel.target_name} ({confidence_info})")

        return "\n".join(parts)


class ContextAssembler:
    """Load symbols, relations, and context for a batch of retrieved chunks.

    Per spec §11.3 the batch flow is:
        Top-K Chunk IDs
        -> one query for associated Symbols
        -> one query for all outbound Relations
        -> one query for target Symbols
        -> group by Chunk in memory
        -> Token Budget truncation
    """

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        max_token_budget: int = 100000,
    ) -> None:
        self._sessions = sessions
        self._max_token_budget = max_token_budget

    async def assemble(
        self,
        scored: Sequence[ScoredChunk],
    ) -> tuple[AssembledContext, ...]:
        """Enrich each scored chunk with its symbols and outbound relations."""
        if not scored:
            return ()
        chunk_ids = [item.chunk.id for item in scored]

        async with self._sessions() as session:
            # One query for associated Symbols
            symbols = list(
                await session.scalars(select(CodeSymbol).where(CodeSymbol.chunk_id.in_(chunk_ids)))
            )
            symbols_by_chunk: dict[int, list[CodeSymbol]] = {cid: [] for cid in chunk_ids}
            for sym in symbols:
                if sym.chunk_id is not None:
                    symbols_by_chunk.setdefault(sym.chunk_id, []).append(sym)

            symbol_ids = [sym.id for sym in symbols]

            # One query for all outbound Relations
            relations = (
                list(
                    await session.scalars(
                        select(CodeRelation).where(CodeRelation.source_symbol_id.in_(symbol_ids))
                    )
                )
                if symbol_ids
                else []
            )
            relations_by_symbol: dict[int, list[CodeRelation]] = {}
            for rel in relations:
                relations_by_symbol.setdefault(rel.source_symbol_id, []).append(rel)

            # One query for target Symbols (resolved references)
            target_ids = [
                rel.target_symbol_id for rel in relations if rel.target_symbol_id is not None
            ]
            target_symbols: dict[int, CodeSymbol] = {}
            if target_ids:
                target_rows = list(
                    await session.scalars(select(CodeSymbol).where(CodeSymbol.id.in_(target_ids)))
                )
                target_symbols = {sym.id: sym for sym in target_rows}

        # Group by chunk in memory, with Token Budget truncation
        token_budget = 0
        assembled: list[AssembledContext] = []
        for item in scored:
            ch_symbols = symbols_by_chunk.get(item.chunk.id, [])
            ch_relations: list[CodeRelation] = []
            for sym in ch_symbols:
                ch_relations.extend(relations_by_symbol.get(sym.id, []))

            ch_target_symbols = {
                rel.target_symbol_id: target_symbols[rel.target_symbol_id]
                for rel in ch_relations
                if rel.target_symbol_id is not None and rel.target_symbol_id in target_symbols
            }

            ctx = AssembledContext(
                chunk_id=item.chunk.id,
                language=item.chunk.language,
                relative_path=item.chunk.relative_path,
                start_line=item.chunk.start_line,
                end_line=item.chunk.end_line,
                symbol_name=item.chunk.symbol_name,
                symbol_type=item.chunk.symbol_type,
                qualified_name=item.chunk.qualified_name,
                code=item.chunk.content,
                neighbors=item.chunk.neighbors,
                symbols=tuple(ch_symbols),
                relations=tuple(ch_relations),
                target_symbols=ch_target_symbols,
                rrf_score=item.rrf_score,
            )
            token_budget += ctx.estimated_tokens
            if token_budget > self._max_token_budget:
                break
            assembled.append(ctx)

        return tuple(assembled)
