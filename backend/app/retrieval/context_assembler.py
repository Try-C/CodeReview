"""Dynamic context assembly: enrich retrieved chunks with symbols and relations."""

from collections.abc import Sequence
from dataclasses import dataclass

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
    neighbors: dict[str, object]
    symbols: tuple[CodeSymbol, ...]
    relations: tuple[CodeRelation, ...]
    rrf_score: float

    def format_for_llm(self) -> str:
        """Produce a compact textual representation suitable for an LLM context window."""
        header = (
            f"[{self.chunk_id}] {self.relative_path}:{self.start_line}-{self.end_line}"
        )
        if self.symbol_name:
            header += f" {self.symbol_type or 'symbol'} {self.qualified_name or self.symbol_name}"
        parts = [header]
        parts.append("```" + (self.language or ""))
        parts.append(self.code.rstrip())
        parts.append("```")
        if self.relations:
            parts.append("references:")
            for rel in self.relations:
                parts.append(
                    f"  {rel.relation_type} → {rel.target_name}"
                    f" (confidence={rel.confidence:.2f}, {rel.resolution_status})"
                )
        return "\n".join(parts)


class ContextAssembler:
    """Load symbols, relations, and context for a batch of retrieved chunks."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def assemble(
        self,
        scored: Sequence[ScoredChunk],
    ) -> tuple[AssembledContext, ...]:
        """Enrich each scored chunk with its symbols and outbound relations."""
        if not scored:
            return ()
        chunk_ids = [item.chunk.id for item in scored]

        async with self._sessions() as session:
            symbols = list(
                await session.scalars(
                    select(CodeSymbol).where(CodeSymbol.chunk_id.in_(chunk_ids))
                )
            )
            symbols_by_chunk: dict[int, list[CodeSymbol]] = {cid: [] for cid in chunk_ids}
            for sym in symbols:
                if sym.chunk_id is not None:
                    symbols_by_chunk.setdefault(sym.chunk_id, []).append(sym)

            symbol_ids = [sym.id for sym in symbols]
            relations = (
                list(
                    await session.scalars(
                        select(CodeRelation).where(
                            CodeRelation.source_symbol_id.in_(symbol_ids)
                        )
                    )
                )
                if symbol_ids
                else []
            )
            relations_by_symbol: dict[int, list[CodeRelation]] = {}
            for rel in relations:
                relations_by_symbol.setdefault(rel.source_symbol_id, []).append(rel)

        return tuple(
            AssembledContext(
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
                symbols=tuple(symbols_by_chunk.get(item.chunk.id, [])),
                relations=tuple(
                    rel
                    for sym in symbols_by_chunk.get(item.chunk.id, [])
                    for rel in relations_by_symbol.get(sym.id, [])
                ),
                rrf_score=item.rrf_score,
            )
            for item in scored
        )
