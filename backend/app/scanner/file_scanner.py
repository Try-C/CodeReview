"""Filesystem scanner for server-owned uploaded project trees."""

import os
from collections import Counter, defaultdict
from collections.abc import Collection
from pathlib import Path, PurePosixPath

from app.scanner.file_filter import FileFilter
from app.scanner.priority import PriorityClassifier
from app.scanner.schemas import (
    LanguageScanStats,
    ScanCoverage,
    ScanFileResult,
    ScanReport,
)
from app.storage.local import LocalProjectStorage


class FileScanner:
    """Scan only server-owned storage and classify every registered source file."""

    def __init__(
        self,
        storage: LocalProjectStorage,
        file_filter: FileFilter,
        priority_classifier: PriorityClassifier,
    ) -> None:
        self._storage = storage
        self._filter = file_filter
        self._priority_classifier = priority_classifier

    def scan(self, storage_key: str, registered_paths: Collection[str]) -> ScanReport:
        """Return stable outcomes for physical, missing, filtered and unexpected files."""
        root = self._storage.project_path(storage_key)
        expected = set(registered_paths)
        outcomes: dict[str, ScanFileResult] = {}
        unregistered: list[ScanFileResult] = []
        discovered_files = 0

        for current_root, directories, filenames in os.walk(root, followlinks=False):
            directories.sort()
            filenames.sort()
            current = Path(current_root)
            for filename in filenames:
                discovered_files += 1
                path = current / filename
                relative_path = path.relative_to(root).as_posix()
                if relative_path not in expected:
                    unregistered.append(
                        ScanFileResult(
                            relative_path=relative_path,
                            status="skipped",
                            size=self._safe_size(path),
                            reason="UNREGISTERED_FILE",
                        )
                    )
                    continue
                outcomes[relative_path] = self._scan_registered(path, relative_path)

        for relative_path in sorted(expected - outcomes.keys()):
            reason = (
                "UNSAFE_REGISTERED_PATH"
                if not self._is_safe_relative_path(relative_path)
                else "FILE_MISSING"
            )
            outcomes[relative_path] = ScanFileResult(
                relative_path=relative_path,
                status="failed",
                reason=reason,
            )

        files = tuple(
            sorted(
                (*outcomes.values(), *unregistered),
                key=lambda result: result.relative_path,
            )
        )
        included = tuple(result for result in outcomes.values() if result.status == "included")
        skipped = tuple(result for result in outcomes.values() if result.status == "skipped")
        failed = tuple(result for result in outcomes.values() if result.status == "failed")
        language_accumulator: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
        priority_stats: Counter[str] = Counter()
        for result in included:
            if result.language is None or result.priority is None:
                raise RuntimeError("Included scan results require language and priority")
            totals = language_accumulator[result.language]
            totals[0] += 1
            totals[1] += result.line_count
            totals[2] += result.size
            priority_stats[result.priority] += 1

        language_stats = {
            language: LanguageScanStats(files=totals[0], lines=totals[1], size=totals[2])
            for language, totals in sorted(language_accumulator.items())
        }
        main_language = (
            min(
                language_stats,
                key=lambda language: (-language_stats[language].files, language),
            )
            if language_stats
            else None
        )
        registered_count = len(expected)
        coverage = ScanCoverage(
            registered_files=registered_count,
            discovered_files=discovered_files,
            included_files=len(included),
            skipped_files=len(skipped),
            failed_files=len(failed),
            included_lines=sum(result.line_count for result in included),
            included_size=sum(result.size for result in included),
            coverage_rate=len(included) / registered_count if registered_count else 1.0,
        )
        return ScanReport(
            files=files,
            coverage=coverage,
            language_stats=language_stats,
            priority_stats={
                priority: priority_stats.get(priority, 0) for priority in ("high", "medium", "low")
            },
            main_language=main_language,
        )

    def _scan_registered(self, path: Path, relative_path: str) -> ScanFileResult:
        if not self._is_safe_relative_path(relative_path):
            return ScanFileResult(
                relative_path=relative_path,
                status="failed",
                reason="UNSAFE_REGISTERED_PATH",
            )
        try:
            size = path.stat().st_size
        except OSError:
            return ScanFileResult(
                relative_path=relative_path,
                status="failed",
                reason="FILE_STAT_FAILED",
            )
        exclusion_reason = self._filter.exclusion_reason(relative_path, size)
        if exclusion_reason is not None:
            return ScanFileResult(
                relative_path=relative_path,
                status="skipped",
                size=size,
                reason=exclusion_reason,
            )
        try:
            data = path.read_bytes()
        except OSError:
            return ScanFileResult(
                relative_path=relative_path,
                status="failed",
                size=size,
                reason="FILE_READ_FAILED",
            )
        if b"\x00" in data:
            return ScanFileResult(
                relative_path=relative_path,
                status="skipped",
                size=size,
                reason="BINARY_FILE",
            )
        text = self._decode(data)
        if text is None:
            return ScanFileResult(
                relative_path=relative_path,
                status="skipped",
                size=size,
                reason="UNSUPPORTED_ENCODING",
            )
        language = self._filter.language_for(relative_path)
        if language not in {"java", "python"}:
            raise RuntimeError("The file filter returned an unsupported language")
        return ScanFileResult(
            relative_path=relative_path,
            status="included",
            language=language,
            size=size,
            line_count=len(text.splitlines()),
            priority=self._priority_classifier.classify(relative_path),
        )

    @staticmethod
    def _decode(data: bytes) -> str | None:
        candidates = ("utf-8-sig", "utf-8") if data.startswith(b"\xef\xbb\xbf") else ("utf-8",)
        for encoding in (*candidates, "gb18030", "gbk"):
            try:
                return data.decode(encoding)
            except UnicodeDecodeError:
                continue
        return None

    @staticmethod
    def _is_safe_relative_path(relative_path: str) -> bool:
        path = PurePosixPath(relative_path)
        return (
            bool(path.parts)
            and not path.is_absolute()
            and "\\" not in relative_path
            and ".." not in path.parts
            and path.as_posix() == relative_path
        )

    @staticmethod
    def _safe_size(path: Path) -> int:
        try:
            return max(path.stat().st_size, 0)
        except OSError:
            return 0
