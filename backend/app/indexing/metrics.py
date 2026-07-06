"""Small reproducible indexing acceptance metrics."""

from collections.abc import Sequence, Set


def recall_at_k[Item](expected: Set[Item], ranked: Sequence[Item], k: int) -> float:
    """Measure the fraction of relevant IDs present in the first k results."""
    if k < 1:
        raise ValueError("k must be positive")
    if not expected:
        return 1.0
    return len(set(expected).intersection(ranked[:k])) / len(expected)
