"""Pure validation rules for untrusted upload manifest paths."""

import re
from pathlib import PurePosixPath

from app.core.config import Settings
from app.core.exceptions import AppError

EXCLUDED_DIRECTORIES = {
    ".git",
    ".gradle",
    ".idea",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".vscode",
    ".venv",
    "__pycache__",
    "build",
    "cache",
    "coverage",
    "dist",
    "generated",
    "generated-sources",
    "logs",
    "node_modules",
    "out",
    "target",
    "venv",
}
WINDOWS_RESERVED_NAMES = {
    "aux",
    "clock$",
    "con",
    "nul",
    "prn",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
}
ILLEGAL_CHARACTER_PATTERN = re.compile(r'[\x00-\x1f<>:"|?*]')
LANGUAGE_EXTENSIONS = {".java": "java", ".py": "python"}


class UploadPolicy:
    """Classify manifest paths using centrally configured P0 limits."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @property
    def max_file_bytes(self) -> int:
        return self._settings.max_single_file_mb * 1024 * 1024

    @property
    def max_project_bytes(self) -> int:
        return self._settings.max_project_size_mb * 1024 * 1024

    def normalize_path(self, raw_path: str) -> str:
        """Return a portable relative path or reject it before filesystem use."""
        if raw_path != raw_path.strip() or "\\" in raw_path:
            self._unsafe_path(raw_path)
        if len(raw_path) > self._settings.max_relative_path_length:
            self._unsafe_path(raw_path)
        path = PurePosixPath(raw_path)
        if path.is_absolute() or not path.parts:
            self._unsafe_path(raw_path)
        for component in path.parts:
            stem = component.split(".", maxsplit=1)[0].casefold()
            if (
                component in {"", ".", ".."}
                or component.endswith((" ", "."))
                or len(component) > 255
                or ILLEGAL_CHARACTER_PATTERN.search(component)
                or stem in WINDOWS_RESERVED_NAMES
            ):
                self._unsafe_path(raw_path)
        normalized = path.as_posix()
        if normalized != raw_path:
            self._unsafe_path(raw_path)
        return normalized

    def language_for(self, relative_path: str) -> str | None:
        """Return an enabled P0 language for an allowlisted extension."""
        language = LANGUAGE_EXTENSIONS.get(PurePosixPath(relative_path).suffix.casefold())
        if language not in self._settings.enabled_languages:
            return None
        return language

    @staticmethod
    def is_excluded(relative_path: str) -> bool:
        """Identify default-excluded build, dependency, cache, and IDE paths."""
        return any(
            component.casefold() in EXCLUDED_DIRECTORIES
            for component in PurePosixPath(relative_path).parts[:-1]
        )

    @staticmethod
    def _unsafe_path(raw_path: str) -> None:
        raise AppError(
            code="UNSAFE_UPLOAD_PATH",
            message="Manifest contains an unsafe relative path",
            status_code=422,
            details={"relative_path": raw_path},
        )
