"""Benchmark metrics for CodeReview Agent evaluation.

Calculates Precision, Recall, F1 and auxiliary metrics per spec §18.4.
All calculations use Python floats; cost calculations in the main system use
Decimal per §5, but benchmark statistics are computed over repeated trials and
Decimal is not required for statistical summaries.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class BenchmarkMetrics:
    """Aggregate evaluation metrics for one benchmark run.

    Attributes:
        precision: TP / (TP + FP), 0 when no predictions.
        recall: TP / (TP + FN), 0 when no ground truth.
        f1: Harmonic mean of precision and recall.
        tp: True positive count.
        fp: False positive count.
        fn: False negative count.
        high_risk_fp_rate: Fraction of High-risk predictions that are FP.
        effective_localization_rate: Fraction of TPs where the predicted
            line range contains the sink_line.
        total_ground_truth: Number of ground truth entries (vulnerable=true).
        total_predictions: Number of predictions submitted.
        recall_at_k: Sorted by predicted relevance, top-K coverage.
        recall_at_k_values: K values used (default [5, 10, 20]).
        matches: Number of matched prediction-ground-truth pairs.
    """

    precision: float
    recall: float
    f1: float
    tp: int
    fp: int
    fn: int
    high_risk_fp_rate: float
    effective_localization_rate: float
    total_ground_truth: int
    total_predictions: int
    recall_at_k: dict[int, float] = field(default_factory=dict)
    recall_at_k_values: list[int] = field(default_factory=lambda: [5, 10, 20])
    matches: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "precision": self.precision,
            "recall": self.recall,
            "f1": self.f1,
            "tp": self.tp,
            "fp": self.fp,
            "fn": self.fn,
            "high_risk_fp_rate": self.high_risk_fp_rate,
            "effective_localization_rate": self.effective_localization_rate,
            "total_ground_truth": self.total_ground_truth,
            "total_predictions": self.total_predictions,
            "recall_at_k": self.recall_at_k,
            "matches": self.matches,
        }


def calculate_precision_recall_f1(
    tp: int,
    fp: int,
    fn: int,
) -> tuple[float, float, float]:
    """Return (precision, recall, f1) from raw counts.

    Precision = 0 when no predictions; Recall = 0 when no ground truth;
    F1 = 0 when both are zero (handles division-by-zero gracefully).
    """
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall > 0 else 0.0
    return precision, recall, f1


def calculate_recall_at_k(
    matched_gt_ids: set[str],
    all_gt_ids: set[str],
    ranked_predictions: list[str],
    k_values: list[int] | None = None,
) -> dict[int, float]:
    """Calculate Recall@K from ranked predictions in descending relevance order.

    Args:
        matched_gt_ids: GT ids that were matched by at least one prediction.
        all_gt_ids: Full set of ground truth ids (vulnerable=true).
        ranked_predictions: Prediction-level identifiers in descending relevance
            order.  Only the first occurrence of each matched GT id counts.
        k_values: K cutoffs to report (default [5, 10, 20]).

    Returns:
        Dict mapping k → recall value.
    """
    if k_values is None:
        k_values = [5, 10, 20]
    total_gt = len(all_gt_ids)
    if total_gt == 0:
        return {k: 0.0 for k in k_values}

    seen: set[str] = set()
    cumulative: dict[int, int] = {}
    for i, pred_id in enumerate(ranked_predictions, start=1):
        if pred_id in matched_gt_ids and pred_id not in seen:
            seen.add(pred_id)
        cumulative[i] = len(seen)

    result: dict[int, float] = {}
    for k in k_values:
        if k < 1:
            result[k] = 0.0
        else:
            hits = cumulative.get(min(k, len(ranked_predictions)), len(seen))
            result[k] = min(hits, total_gt) / total_gt
    return result
