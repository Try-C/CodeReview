"""Validated output contracts for deterministic project scans."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ScanStatus = Literal["included", "skipped", "failed"]
ScanPriority = Literal["high", "medium", "low"]


class ScanFileResult(BaseModel):
    """One deterministic scan outcome, including skipped and failed paths."""

    model_config = ConfigDict(frozen=True)

    relative_path: str = Field(min_length=1, max_length=512)
    status: ScanStatus
    language: Literal["java", "python"] | None = None
    size: int = Field(default=0, ge=0)
    line_count: int = Field(default=0, ge=0)
    priority: ScanPriority | None = None
    reason: str | None = None


class LanguageScanStats(BaseModel):
    """Included-file distribution for one supported language."""

    model_config = ConfigDict(frozen=True)

    files: int = Field(ge=0)
    lines: int = Field(ge=0)
    size: int = Field(ge=0)


class ScanCoverage(BaseModel):
    """Coverage counters measured against database-registered project files."""

    model_config = ConfigDict(frozen=True)

    registered_files: int = Field(ge=0)
    discovered_files: int = Field(ge=0)
    included_files: int = Field(ge=0)
    skipped_files: int = Field(ge=0)
    failed_files: int = Field(ge=0)
    included_lines: int = Field(ge=0)
    included_size: int = Field(ge=0)
    coverage_rate: float = Field(ge=0, le=1)


class ScanReport(BaseModel):
    """Complete, serializable scanner output used by later pipeline stages."""

    model_config = ConfigDict(frozen=True)

    files: tuple[ScanFileResult, ...]
    coverage: ScanCoverage
    language_stats: dict[Literal["java", "python"], LanguageScanStats]
    priority_stats: dict[ScanPriority, int]
    main_language: Literal["java", "python"] | None
