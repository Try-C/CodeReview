"""Language adapter registration and deterministic resolution."""

from pathlib import PurePath

from app.languages.base import LanguageAdapter


class UnsupportedLanguageError(ValueError):
    """Raised when no registered adapter claims a source file."""


class LanguageAdapterRegistry:
    """Resolve adapters without leaking language conditionals to callers."""

    def __init__(self) -> None:
        self._adapters: dict[str, LanguageAdapter] = {}

    @property
    def languages(self) -> tuple[str, ...]:
        return tuple(self._adapters)

    def register(self, adapter: LanguageAdapter) -> None:
        if adapter.language in self._adapters:
            raise ValueError(f"An adapter is already registered for {adapter.language}")
        self._adapters[adapter.language] = adapter

    def resolve(self, file_path: str, content: str) -> LanguageAdapter:
        suffix = PurePath(file_path).suffix.casefold()
        extension_matches = [
            adapter for adapter in self._adapters.values() if suffix in adapter.extensions
        ]
        for adapter in extension_matches:
            if adapter.detect(file_path, content):
                return adapter
        for adapter in self._adapters.values():
            if adapter not in extension_matches and adapter.detect(file_path, content):
                return adapter
        raise UnsupportedLanguageError(f"Unsupported source language: {file_path}")
