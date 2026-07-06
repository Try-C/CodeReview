"""Evaluation runner for CodeReview Agent benchmark.

Implements the matching rules from spec §18.3 and produces
BenchmarkMetrics per §18.4.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from benchmark.metrics import (
    BenchmarkMetrics,
    calculate_precision_recall_f1,
)

logger = logging.getLogger(__name__)

# ── Data types ──────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class GroundTruthEntry:
    """One row of ground truth per spec §18.2."""

    id: str
    language: str
    category: str
    relative_path: str
    cwe_id: str
    sink_line: int
    start_line: int
    end_line: int
    vulnerable: bool = True

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> GroundTruthEntry:
        return cls(
            id=d["id"],
            language=d["language"],
            category=d["category"],
            relative_path=d["relative_path"],
            cwe_id=d.get("cwe_id", ""),
            sink_line=d.get("sink_line", 0) or 0,
            start_line=d.get("start_line", 0) or 0,
            end_line=d.get("end_line", 0) or 0,
            vulnerable=d.get("vulnerable", True),
        )


@dataclass(frozen=True, slots=True)
class PredictionEntry:
    """One prediction produced by a predictor or agent."""

    relative_path: str
    start_line: int
    end_line: int
    language: str
    category: str
    cwe_id: str = ""
    risk_level: str = "Medium"
    fingerprint: str = ""

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> PredictionEntry:
        return cls(
            relative_path=d["relative_path"],
            start_line=d.get("start_line", 0),
            end_line=d.get("end_line", 0),
            language=d["language"],
            category=d["category"],
            cwe_id=d.get("cwe_id", ""),
            risk_level=d.get("risk_level", "Medium"),
            fingerprint=d.get("fingerprint", ""),
        )


@dataclass(frozen=True, slots=True)
class MatchedResult:
    """One successful match between a prediction and a ground truth entry."""

    ground_truth_id: str
    prediction_index: int
    overlap_ratio: float  # fraction of GT interval covered by prediction


@dataclass(frozen=True, slots=True)
class EvaluationResult:
    """Full result of one benchmark evaluation run."""

    metrics: BenchmarkMetrics
    matches: tuple[MatchedResult, ...] = ()
    unmatched_gt_ids: tuple[str, ...] = ()
    unmatched_pred_indices: tuple[int, ...] = ()
    language: str = ""


# ── Predictor protocol ──────────────────────────────────────────────────────


class Predictor(Protocol):
    """A callable that produces predictions from a dataset directory."""

    def predict(self, dataset_root: str, language: str) -> list[PredictionEntry]: ...


# ── Matching logic (§18.3) ──────────────────────────────────────────────────


def _normalize_path(p: str) -> str:
    """Normalise a relative path for deterministic cross-platform comparison."""
    return str(Path(p.replace("\\", "/")))


def _overlap_ratio(
    pred_start: int,
    pred_end: int,
    gt_start: int,
    gt_end: int,
) -> float:
    """Fraction of the GT interval [gt_start, gt_end] covered by the prediction."""
    if gt_end < gt_start or pred_end < pred_start:
        return 0.0
    overlap_start = max(pred_start, gt_start)
    overlap_end = min(pred_end, gt_end)
    if overlap_start > overlap_end:
        return 0.0
    overlap = overlap_end - overlap_start + 1
    gt_len = gt_end - gt_start + 1
    return overlap / gt_len


def _prediction_covers_sink(
    pred: PredictionEntry,
    gt: GroundTruthEntry,
) -> bool:
    """Check whether the prediction covers the ground truth sink line."""
    return pred.start_line <= gt.sink_line <= pred.end_line


def _is_candidate_match(
    pred: PredictionEntry,
    gt: GroundTruthEntry,
) -> bool:
    """Return True if pred and gt satisfy the four matching rules (§18.3)."""
    # 1. Same language.
    if pred.language != gt.language:
        return False
    # 2. Normalised relative path exact match.
    if _normalize_path(pred.relative_path) != _normalize_path(gt.relative_path):
        return False
    # 3. Same category; Security additionally requires same CWE.
    if pred.category != gt.category:
        return False
    if gt.category == "security" and pred.cwe_id != gt.cwe_id:
        return False
    # 4. Prediction contains sink_line OR overlap ≥ 50%.
    if _prediction_covers_sink(pred, gt):
        return True
    ratio = _overlap_ratio(pred.start_line, pred.end_line, gt.start_line, gt.end_line)
    return ratio >= 0.5


def match_predictions(
    ground_truth: list[GroundTruthEntry],
    predictions: list[PredictionEntry],
) -> tuple[list[MatchedResult], list[str], list[int]]:
    """Deterministic one-to-one maximum-cardinality matching (§18.3).

    Uses augmenting paths so a locally attractive pair cannot reduce the total
    number of matches. Candidate ordering only chooses among equally large
    matchings; it does not change TP count. Duplicate predictions are FP.

    Returns:
        (matches, unmatched_gt_ids, unmatched_pred_indices)
    """
    vulnerable = [gt for gt in ground_truth if gt.vulnerable]

    adjacency: dict[int, list[int]] = {}
    for pi, pred in enumerate(predictions):
        candidate_gt_indices = [
            gi for gi, gt in enumerate(vulnerable) if _is_candidate_match(pred, gt)
        ]
        candidate_gt_indices.sort(
            key=lambda gi: (
                -int(_prediction_covers_sink(pred, vulnerable[gi])),
                -_overlap_ratio(
                    pred.start_line,
                    pred.end_line,
                    vulnerable[gi].start_line,
                    vulnerable[gi].end_line,
                ),
                vulnerable[gi].id,
            )
        )
        adjacency[pi] = candidate_gt_indices

    prediction_order = sorted(
        range(len(predictions)),
        key=lambda pi: (
            _normalize_path(predictions[pi].relative_path),
            predictions[pi].start_line,
            predictions[pi].end_line,
            predictions[pi].language,
            predictions[pi].category,
            predictions[pi].cwe_id,
            predictions[pi].risk_level,
            predictions[pi].fingerprint,
            pi,
        ),
    )
    gt_to_prediction: dict[int, int] = {}

    def assign(pi: int, visited_gt: set[int]) -> bool:
        for gi in adjacency[pi]:
            if gi in visited_gt:
                continue
            visited_gt.add(gi)
            current_pi = gt_to_prediction.get(gi)
            if current_pi is None or assign(current_pi, visited_gt):
                gt_to_prediction[gi] = pi
                return True
        return False

    for pi in prediction_order:
        assign(pi, set())

    matches = [
        MatchedResult(
            ground_truth_id=vulnerable[gi].id,
            prediction_index=pi,
            overlap_ratio=_overlap_ratio(
                predictions[pi].start_line,
                predictions[pi].end_line,
                vulnerable[gi].start_line,
                vulnerable[gi].end_line,
            ),
        )
        for gi, pi in sorted(gt_to_prediction.items(), key=lambda item: vulnerable[item[0]].id)
    ]
    matched_gt = set(gt_to_prediction)
    matched_pred = set(gt_to_prediction.values())
    unmatched_gt_ids = [gt.id for i, gt in enumerate(vulnerable) if i not in matched_gt]
    unmatched_pred_indices = [i for i in range(len(predictions)) if i not in matched_pred]

    return matches, unmatched_gt_ids, unmatched_pred_indices


# ── Runner ──────────────────────────────────────────────────────────────────


class EvaluationRunner:
    """Load ground truth, run a predictor, match, and compute metrics."""

    def __init__(self, ground_truth_dir: str) -> None:
        self._gt_dir = Path(ground_truth_dir)

    def load_ground_truth(self, language: str) -> list[GroundTruthEntry]:
        """Load ground truth JSON for *language* from disk."""
        path = self._gt_dir / f"{language}.json"
        if not path.is_file():
            raise FileNotFoundError(f"Ground truth not found: {path}")
        data = json.loads(path.read_text(encoding="utf-8"))
        return [GroundTruthEntry.from_dict(e) for e in data["entries"]]

    def evaluate(
        self,
        predictor: Predictor,
        dataset_root: str,
        language: str,
        *,
        recall_at_k_values: list[int] | None = None,
    ) -> EvaluationResult:
        """Run full evaluation: predict → match → compute metrics.

        Args:
            predictor: Callable that produces PredictionEntry list.
            dataset_root: Path to the datasets/ directory.
            language: 'java' or 'python'.
            recall_at_k_values: K cutoffs for Recall@K (default [5, 10, 20]).

        Returns:
            EvaluationResult with metrics and match details.
        """
        if recall_at_k_values is None:
            recall_at_k_values = [5, 10, 20]

        gt = self.load_ground_truth(language)
        predictions = predictor.predict(dataset_root, language)

        matches, unmatched_gt_ids, unmatched_pred_indices = match_predictions(gt, predictions)

        vulnerable = [g for g in gt if g.vulnerable]
        tp = len(matches)
        fp = len(predictions) - tp
        fn = len(vulnerable) - tp

        precision, recall, f1 = calculate_precision_recall_f1(tp, fp, fn)

        # High-risk false positive rate.
        high_risk_preds = [i for i, p in enumerate(predictions) if p.risk_level == "High"]
        matched_prediction_indices = {match.prediction_index for match in matches}
        high_risk_fp = len([i for i in high_risk_preds if i not in matched_prediction_indices])
        high_risk_fp_rate = high_risk_fp / len(high_risk_preds) if high_risk_preds else 0.0

        # Effective localization rate: TPs where prediction covers sink_line.
        localized = 0
        for m in matches:
            pred = predictions[m.prediction_index]
            gt_entry = next(g for g in vulnerable if g.id == m.ground_truth_id)
            if _prediction_covers_sink(pred, gt_entry):
                localized += 1
        effective_localization_rate = localized / tp if tp > 0 else 0.0

        # Prediction order is the predictor's relevance ranking. Re-match each
        # prefix so a duplicate or globally unmatched prediction cannot borrow
        # a match made by a lower-ranked prediction.
        recall_at_k: dict[int, float] = {}
        for k in recall_at_k_values:
            if k < 1 or not vulnerable:
                recall_at_k[k] = 0.0
                continue
            top_k_matches, _, _ = match_predictions(gt, predictions[:k])
            recall_at_k[k] = len(top_k_matches) / len(vulnerable)

        metrics = BenchmarkMetrics(
            precision=precision,
            recall=recall,
            f1=f1,
            tp=tp,
            fp=fp,
            fn=fn,
            high_risk_fp_rate=high_risk_fp_rate,
            effective_localization_rate=effective_localization_rate,
            total_ground_truth=len(vulnerable),
            total_predictions=len(predictions),
            recall_at_k=recall_at_k,
            recall_at_k_values=recall_at_k_values,
            matches=tp,
        )

        return EvaluationResult(
            metrics=metrics,
            matches=tuple(matches),
            unmatched_gt_ids=tuple(unmatched_gt_ids),
            unmatched_pred_indices=tuple(unmatched_pred_indices),
            language=language,
        )


# ── Helpers ─────────────────────────────────────────────────────────────────


def load_ground_truth(ground_truth_dir: str, language: str) -> list[GroundTruthEntry]:
    """Convenience: load a single language's ground truth."""
    runner = EvaluationRunner(ground_truth_dir)
    return runner.load_ground_truth(language)
