"""Reciprocal Rank Fusion for merging ranked retrieval lists."""

from collections.abc import Iterable


def fuse_rrf(
    ranked_lists: Iterable[Iterable[tuple[int, float]]],
    *,
    k: int = 60,
    top_k: int = 10,
) -> list[tuple[int, float]]:
    """Combine multiple ranked result sets into one score-sorted list.

    Each input is an iterable of (item_id, _) already ordered by descending
    relevance.  The raw score from each sub-system is discarded; RRF only
    considers rank position.

    score(item) = Σ 1 / (k + rank_position)  for each list where it appears.

    Ranks are 1-indexed.  Items missing from a list contribute 0 for that list.
    """
    scores: dict[int, float] = {}
    for ranked in ranked_lists:
        for position, (item_id, _) in enumerate(ranked, start=1):
            contribution = 1.0 / (k + position)
            scores[item_id] = scores.get(item_id, 0.0) + contribution
    return sorted(scores.items(), key=lambda pair: pair[1], reverse=True)[:top_k]
