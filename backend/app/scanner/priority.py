"""Review-priority classification based only on normalized path metadata."""

from pathlib import PurePosixPath

from app.scanner.schemas import ScanPriority

HIGH_PRIORITY_MARKERS = {
    "api",
    "auth",
    "authentication",
    "authorization",
    "config",
    "controller",
    "controllers",
    "endpoint",
    "endpoints",
    "middleware",
    "permission",
    "permissions",
    "route",
    "routes",
    "security",
    "settings",
}
LOW_PRIORITY_DIRECTORIES = {
    "fixture",
    "fixtures",
    "migration",
    "migrations",
    "test",
    "tests",
}


class PriorityClassifier:
    """Rank review value without reading or executing uploaded source code."""

    def classify(self, relative_path: str) -> ScanPriority:
        """Return high for boundary/security code, low for tests and migrations."""
        path = PurePosixPath(relative_path)
        components = {component.casefold() for component in path.parts[:-1]}
        stem_tokens = {
            token for token in path.stem.casefold().replace("-", "_").split("_") if token
        }
        if components & LOW_PRIORITY_DIRECTORIES or path.name.casefold().startswith("test_"):
            return "low"
        if components & HIGH_PRIORITY_MARKERS or stem_tokens & HIGH_PRIORITY_MARKERS:
            return "high"
        return "medium"
