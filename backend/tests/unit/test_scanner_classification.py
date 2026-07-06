"""Unit coverage for deterministic scan filtering and prioritization."""

import pytest

from app.core.config import Settings
from app.scanner import FileFilter, PriorityClassifier


@pytest.fixture
def file_filter() -> FileFilter:
    return FileFilter(Settings(_env_file=None, max_single_file_mb=1))


@pytest.mark.parametrize(
    ("relative_path", "size", "reason"),
    [
        ("node_modules/tool.py", 10, "EXCLUDED_PATH"),
        ("src/generated.py", 10, "GENERATED_FILE"),
        ("src/client.min.java", 10, "GENERATED_FILE"),
        ("src/readme.md", 10, "UNSUPPORTED_FILE_TYPE"),
        ("src/large.py", 1024 * 1024 + 1, "SINGLE_FILE_SIZE_EXCEEDED"),
        ("src/service.py", 10, None),
    ],
)
def test_file_filter_returns_stable_reason_codes(
    file_filter: FileFilter,
    relative_path: str,
    size: int,
    reason: str | None,
) -> None:
    assert file_filter.exclusion_reason(relative_path, size) == reason


def test_file_filter_honors_enabled_languages() -> None:
    python_only = FileFilter(Settings(_env_file=None, enabled_languages=("python",)))

    assert python_only.language_for("src/main.py") == "python"
    assert python_only.language_for("src/Main.java") is None


@pytest.mark.parametrize(
    ("relative_path", "priority"),
    [
        ("src/api/orders.py", "high"),
        ("src/security/TokenService.java", "high"),
        ("src/domain/order.py", "medium"),
        ("tests/test_order.py", "low"),
        ("src/test/java/OrderTest.java", "low"),
    ],
)
def test_priority_classifier_uses_review_value_markers(
    relative_path: str,
    priority: str,
) -> None:
    assert PriorityClassifier().classify(relative_path) == priority
