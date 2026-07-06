"""Deterministic path and size filtering for project scans."""

from pathlib import PurePosixPath

from app.core.config import Settings

LANGUAGE_EXTENSIONS = {".java": "java", ".py": "python"}
EXCLUDED_DIRECTORIES = {
    ".git",
    ".idea",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    ".vscode",
    "__pycache__",
    "build",
    "cache",
    "coverage",
    "dist",
    "generated",
    "generated-sources",
    "logs",
    "node_modules",
    "target",
    "venv",
}
LOCK_FILENAMES = {
    "composer.lock",
    "package-lock.json",
    "pipfile.lock",
    "pnpm-lock.yaml",
    "poetry.lock",
    "yarn.lock",
}
GENERATED_FILE_SUFFIXES = (
    ".designer.java",
    ".generated.java",
    ".generated.py",
    ".min.java",
    ".min.py",
)
GENERATED_FILE_NAMES = {
    "generated.java",
    "generated.py",
}


class FileFilter:
    """Apply the P0 language allowlist and low-value file exclusions."""

    def __init__(self, settings: Settings) -> None:
        self._enabled_languages = frozenset(settings.enabled_languages)
        self._max_file_bytes = settings.max_single_file_mb * 1024 * 1024

    def language_for(self, relative_path: str) -> str | None:
        """Return the enabled language represented by a path extension."""
        language = LANGUAGE_EXTENSIONS.get(PurePosixPath(relative_path).suffix.casefold())
        return language if language in self._enabled_languages else None

    def exclusion_reason(self, relative_path: str, size: int) -> str | None:
        """Return a stable reason code when a discovered path is not reviewable."""
        path = PurePosixPath(relative_path)
        components = tuple(component.casefold() for component in path.parts[:-1])
        filename = path.name.casefold()
        if any(component in EXCLUDED_DIRECTORIES for component in components):
            return "EXCLUDED_PATH"
        if filename in LOCK_FILENAMES:
            return "LOCK_FILE"
        if filename in GENERATED_FILE_NAMES or filename.endswith(GENERATED_FILE_SUFFIXES):
            return "GENERATED_FILE"
        if self.language_for(relative_path) is None:
            return "UNSUPPORTED_FILE_TYPE"
        if size > self._max_file_bytes:
            return "SINGLE_FILE_SIZE_EXCEEDED"
        return None
