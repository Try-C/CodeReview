"""Extensible contract implemented by every supported language."""

from abc import ABC, abstractmethod

from app.languages.schemas import ParseResult


class LanguageAdapter(ABC):
    """Keep all language-specific detection and parsing behind one boundary."""

    language: str
    extensions: frozenset[str]

    @abstractmethod
    def detect(self, file_path: str, content: str) -> bool:
        """Return whether this adapter owns the supplied source."""

    @abstractmethod
    def parse(self, file_path: str, content: str) -> ParseResult:
        """Parse source without executing, importing, or compiling it."""

    def risk_hints(self) -> tuple[str, ...]:
        return ()

    def normalize_query(self, query: str) -> str:
        return query.strip()
