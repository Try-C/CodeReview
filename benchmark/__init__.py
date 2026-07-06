"""CodeReview Agent benchmark harness — ground truth, metrics, and evaluation runner."""

from benchmark.metrics import (
    BenchmarkMetrics,
    calculate_precision_recall_f1,
    calculate_recall_at_k,
)
from benchmark.runner import (
    EvaluationResult,
    EvaluationRunner,
    GroundTruthEntry,
    MatchedResult,
    PredictionEntry,
)

__all__ = [
    "BenchmarkMetrics",
    "EvaluationResult",
    "EvaluationRunner",
    "GroundTruthEntry",
    "MatchedResult",
    "PredictionEntry",
    "calculate_precision_recall_f1",
    "calculate_recall_at_k",
]
