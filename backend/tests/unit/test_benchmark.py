"""Unit tests for benchmark metrics, matching, and fake predictor baseline.

Per spec §19.1, these tests must verify Precision/Recall/F1, the matching
rules (§18.3), and that the FakePredictor produces the expected results.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# The benchmark package lives at the project root, not inside backend.
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from benchmark.metrics import (  # noqa: E402
    BenchmarkMetrics,
    calculate_precision_recall_f1,
    calculate_recall_at_k,
)
from benchmark.predictors.fake_predictor import FakePredictor  # noqa: E402
from benchmark.runner import (  # noqa: E402
    EvaluationRunner,
    GroundTruthEntry,
    PredictionEntry,
    _is_candidate_match,
    _normalize_path,
    _overlap_ratio,
    _prediction_covers_sink,
    match_predictions,
)

# ── Path helpers ────────────────────────────────────────────────────────────

_GT_DIR = str(_PROJECT_ROOT / "benchmark" / "ground_truth")
_DATASETS = str(_PROJECT_ROOT / "benchmark" / "datasets")
_FAKE_DIR = str(_PROJECT_ROOT / "benchmark" / "predictors" / "fake_predictions")

# ── Helpers ─────────────────────────────────────────────────────────────────


def _make_gt(
    id: str = "gt-1",
    language: str = "java",
    category: str = "security",
    path: str = "src/Foo.java",
    cwe: str = "CWE-89",
    sink: int = 10,
    start: int = 8,
    end: int = 12,
    vulnerable: bool = True,
) -> GroundTruthEntry:
    return GroundTruthEntry(
        id=id,
        language=language,
        category=category,
        relative_path=path,
        cwe_id=cwe,
        sink_line=sink,
        start_line=start,
        end_line=end,
        vulnerable=vulnerable,
    )


def _make_pred(
    path: str = "src/Foo.java",
    start: int = 8,
    end: int = 12,
    language: str = "java",
    category: str = "security",
    cwe: str = "CWE-89",
    risk: str = "Medium",
) -> PredictionEntry:
    return PredictionEntry(
        relative_path=path,
        start_line=start,
        end_line=end,
        language=language,
        category=category,
        cwe_id=cwe,
        risk_level=risk,
    )


# ── Metrics tests (§19.1 - Precision/Recall/F1) ─────────────────────────────


class TestPrecisionRecallF1:
    def test_perfect(self) -> None:
        p, r, f1 = calculate_precision_recall_f1(tp=10, fp=0, fn=0)
        assert p == 1.0
        assert r == 1.0
        assert f1 == 1.0

    def test_all_wrong(self) -> None:
        p, r, f1 = calculate_precision_recall_f1(tp=0, fp=10, fn=10)
        assert p == 0.0
        assert r == 0.0
        assert f1 == 0.0

    def test_mixed(self) -> None:
        p, r, f1 = calculate_precision_recall_f1(tp=5, fp=3, fn=3)
        assert p == 5 / 8
        assert r == 5 / 8
        assert f1 == 5 / 8  # when P == R, F1 == P

    def test_no_ground_truth(self) -> None:
        p, r, f1 = calculate_precision_recall_f1(tp=0, fp=0, fn=0)
        assert p == 0.0
        assert r == 0.0
        assert f1 == 0.0

    def test_no_predictions(self) -> None:
        p, r, f1 = calculate_precision_recall_f1(tp=0, fp=0, fn=5)
        assert p == 0.0
        assert r == 0.0
        assert f1 == 0.0


class TestRecallAtK:
    def test_all_found_in_top_k(self) -> None:
        matched = {"a", "b", "c"}
        all_gt = {"a", "b", "c", "d", "e"}
        ranked = ["a", "b", "c", "x", "y"]
        result = calculate_recall_at_k(matched, all_gt, ranked, [3, 5])
        assert result[3] == 3 / 5  # a, b, c found in first 3
        assert result[5] == 3 / 5  # only 3 found total

    def test_none_found(self) -> None:
        matched: set[str] = set()
        all_gt = {"a", "b"}
        ranked = ["x", "y"]
        result = calculate_recall_at_k(matched, all_gt, ranked, [5])
        assert result[5] == 0.0

    def test_empty_ground_truth(self) -> None:
        result = calculate_recall_at_k(set(), set(), [], [5])
        assert result[5] == 0.0

    def test_duplicates_not_double_counted(self) -> None:
        matched = {"a"}
        all_gt = {"a"}
        ranked = ["a", "a", "a"]
        result = calculate_recall_at_k(matched, all_gt, ranked, [3])
        assert result[3] == 1.0


# ── Matching tests (§18.3) ──────────────────────────────────────────────────


class TestPathNormalization:
    def test_identical(self) -> None:
        assert _normalize_path("src/Foo.java") == _normalize_path("src/Foo.java")

    def test_trailing_slash_normalized(self) -> None:
        assert _normalize_path("src/foo/") == _normalize_path("src/foo")

    def test_windows_backslash(self) -> None:
        a = _normalize_path("src\\foo\\Bar.java")
        b = _normalize_path("src/foo/Bar.java")
        assert a == b


class TestOverlapRatio:
    def test_exact_match(self) -> None:
        assert _overlap_ratio(10, 20, 10, 20) == 1.0

    def test_partial_overlap(self) -> None:
        # GT [10, 20] length 11, pred [15, 25] overlap [15, 20] length 6
        ratio = _overlap_ratio(15, 25, 10, 20)
        assert ratio == pytest.approx(6 / 11)

    def test_no_overlap(self) -> None:
        assert _overlap_ratio(1, 5, 10, 20) == 0.0

    def test_pred_contains_gt(self) -> None:
        # GT [12, 15] length 4, pred [10, 20] overlap [12, 15] length 4
        assert _overlap_ratio(10, 20, 12, 15) == 1.0

    def test_single_line_both(self) -> None:
        assert _overlap_ratio(5, 5, 5, 5) == 1.0

    def test_inverted_ranges_return_zero(self) -> None:
        assert _overlap_ratio(20, 10, 5, 15) == 0.0


class TestSinkCoverage:
    def test_covers_sink_exact(self) -> None:
        pred = _make_pred(start=10, end=10)
        gt = _make_gt(sink=10, start=10, end=10)
        assert _prediction_covers_sink(pred, gt) is True

    def test_covers_sink_in_range(self) -> None:
        pred = _make_pred(start=5, end=15)
        gt = _make_gt(sink=10, start=8, end=12)
        assert _prediction_covers_sink(pred, gt) is True

    def test_misses_sink(self) -> None:
        pred = _make_pred(start=1, end=5)
        gt = _make_gt(sink=10, start=8, end=12)
        assert _prediction_covers_sink(pred, gt) is False


class TestCandidateMatch:
    def test_full_match(self) -> None:
        pred = _make_pred("src/Foo.java", 8, 12, "java", "security", "CWE-89")
        gt = _make_gt("gt-1", "java", "security", "src/Foo.java", "CWE-89", 10, 8, 12)
        assert _is_candidate_match(pred, gt) is True

    def test_language_mismatch(self) -> None:
        pred = _make_pred(language="python")
        gt = _make_gt(language="java")
        assert _is_candidate_match(pred, gt) is False

    def test_path_mismatch(self) -> None:
        pred = _make_pred(path="src/Bar.java")
        gt = _make_gt(path="src/Foo.java")
        assert _is_candidate_match(pred, gt) is False

    def test_cwe_mismatch_security_category(self) -> None:
        pred = _make_pred(cwe="CWE-20")
        gt = _make_gt(cwe="CWE-89")
        assert _is_candidate_match(pred, gt) is False

    def test_cwe_ignored_for_non_security(self) -> None:
        pred = _make_pred(category="bug", cwe="")
        gt = _make_gt(category="bug", cwe="")
        assert _is_candidate_match(pred, gt) is True

    def test_overlap_50_percent_passes(self) -> None:
        # GT [10, 13] length 4, pred [12, 13] overlap [12, 13] length 2 → 50%
        pred = _make_pred(start=12, end=13)
        gt = _make_gt(sink=99, start=10, end=13)  # sink NOT covered
        # overlap = [12,13] → 2 / 4 = 0.5 → meets threshold
        assert _is_candidate_match(pred, gt) is True

    def test_overlap_below_50_percent_fails(self) -> None:
        # GT [10, 19] length 10, pred [12, 13] overlap [12, 13] length 2 → 20%
        pred = _make_pred(start=12, end=13)
        gt = _make_gt(sink=99, start=10, end=19)
        assert _is_candidate_match(pred, gt) is False


class TestMatching:
    def test_one_to_one_no_duplicate(self) -> None:
        """Two predictions that both match one GT → only one is matched."""
        gt = [_make_gt("gt-1", path="src/A.java", sink=10, start=10, end=10)]
        preds = [
            _make_pred(path="src/A.java", start=10, end=10),
            _make_pred(path="src/A.java", start=10, end=10),
        ]
        matches, unmatched_gt, unmatched_pred = match_predictions(gt, preds)
        assert len(matches) == 1  # second pred is effectively a duplicate → FP
        assert len(unmatched_gt) == 0
        assert len(unmatched_pred) == 1

    def test_empty_inputs(self) -> None:
        matches, _ug, up = match_predictions([], [])
        assert matches == []
        assert _ug == []
        assert up == []

    def test_no_vulnerable_gt(self) -> None:
        gt = [_make_gt(vulnerable=False)]
        preds = [_make_pred()]
        matches, _ug, up = match_predictions(gt, preds)
        assert matches == []
        assert up == [0]  # all predictions unmatched when no vulnerable GT

    def test_prediction_on_safe_file_is_fp(self) -> None:
        """Prediction on a file with no GT entry → FP."""
        gt = [_make_gt("gt-1", path="src/Vuln.java")]
        preds = [_make_pred(path="src/Safe.java")]
        matches, _ug, up = match_predictions(gt, preds)
        assert matches == []
        assert len(up) == 1

    def test_uses_maximum_cardinality_instead_of_greedy_matching(self) -> None:
        """A flexible prediction must be reassigned to preserve two TPs."""
        gt = [
            _make_gt("gt-a", path="src/A.java", sink=10, start=1, end=10),
            _make_gt("gt-b", path="src/A.java", sink=4, start=1, end=4),
        ]
        preds = [
            _make_pred(path="src/A.java", start=1, end=10),
            _make_pred(path="src/A.java", start=5, end=10),
        ]

        matches, unmatched_gt, unmatched_pred = match_predictions(gt, preds)

        assert len(matches) == 2
        assert unmatched_gt == []
        assert unmatched_pred == []

    def test_reported_overlap_ratio_excludes_matching_priority_bonus(self) -> None:
        gt = [_make_gt("gt-1", sink=10, start=1, end=10)]
        preds = [_make_pred(start=1, end=10)]

        matches, _, _ = match_predictions(gt, preds)

        assert matches[0].overlap_ratio == 1.0


# ── Fake predictor tests ────────────────────────────────────────────────────


class TestFakePredictor:
    def test_java_fake_predictions_produce_expected_counts(self) -> None:
        runner = EvaluationRunner(_GT_DIR)
        predictor = FakePredictor(_FAKE_DIR)
        result = runner.evaluate(predictor, _DATASETS, "java")

        m = result.metrics
        # 5 correct matches, 3 FP, 3 FN out of 8 GT
        assert m.tp == 5
        assert m.fp == 3
        assert m.fn == 3
        assert m.total_ground_truth == 8
        assert m.total_predictions == 8
        assert m.precision == pytest.approx(5 / 8)
        assert m.recall == pytest.approx(5 / 8)
        assert m.f1 == pytest.approx(5 / 8)

    def test_python_fake_predictions_produce_expected_counts(self) -> None:
        runner = EvaluationRunner(_GT_DIR)
        predictor = FakePredictor(_FAKE_DIR)
        result = runner.evaluate(predictor, _DATASETS, "python")

        m = result.metrics
        assert m.tp == 5
        assert m.fp == 3
        assert m.fn == 3
        assert m.total_ground_truth == 8
        assert m.total_predictions == 8

    def test_fake_predictor_unknown_language_returns_empty(self) -> None:
        predictor = FakePredictor(_FAKE_DIR)
        preds = predictor.predict(_DATASETS, "ruby")
        assert preds == []

    def test_fake_predictor_loads_valid_entries(self) -> None:
        predictor = FakePredictor(_FAKE_DIR)
        preds = predictor.predict(_DATASETS, "java")
        assert len(preds) == 8
        for p in preds:
            assert isinstance(p, PredictionEntry)
            assert p.language == "java"
            assert p.category == "security"
            assert p.start_line > 0
            assert p.end_line >= p.start_line


# ── Runner tests ────────────────────────────────────────────────────────────


class TestEvaluationRunner:
    def test_load_java_ground_truth(self) -> None:
        runner = EvaluationRunner(_GT_DIR)
        gt = runner.load_ground_truth("java")
        assert len(gt) == 8
        ids = {e.id for e in gt}
        assert "java-sqli-001" in ids
        assert all(e.language == "java" for e in gt)
        assert all(e.category == "security" for e in gt)

    def test_load_python_ground_truth(self) -> None:
        runner = EvaluationRunner(_GT_DIR)
        gt = runner.load_ground_truth("python")
        assert len(gt) == 8
        assert all(e.language == "python" for e in gt)

    def test_missing_ground_truth_raises(self) -> None:
        runner = EvaluationRunner(_GT_DIR)
        with pytest.raises(FileNotFoundError):
            runner.load_ground_truth("ruby")

    def test_evaluate_empty_predictions(self) -> None:
        """A predictor returning nothing → all metrics zero."""
        runner = EvaluationRunner(_GT_DIR)

        class EmptyPredictor:
            def predict(self, dataset_root: str, language: str) -> list[PredictionEntry]:
                return []

        result = runner.evaluate(EmptyPredictor(), _DATASETS, "java")
        m = result.metrics
        assert m.tp == 0
        assert m.fp == 0
        assert m.fn == 8
        assert m.precision == 0.0
        assert m.recall == 0.0
        assert m.f1 == 0.0

    def test_evaluate_perfect_predictions(self) -> None:
        """A predictor that exactly matches all GT entries → perfect score."""
        runner = EvaluationRunner(_GT_DIR)

        class PerfectPredictor:
            def predict(self, dataset_root: str, language: str) -> list[PredictionEntry]:
                gt = runner.load_ground_truth(language)
                return [
                    PredictionEntry(
                        relative_path=e.relative_path,
                        start_line=e.start_line,
                        end_line=e.end_line,
                        language=e.language,
                        category=e.category,
                        cwe_id=e.cwe_id,
                        risk_level="High",
                    )
                    for e in gt
                    if e.vulnerable
                ]

        result = runner.evaluate(PerfectPredictor(), _DATASETS, "java")
        m = result.metrics
        assert m.tp == 8
        assert m.fp == 0
        assert m.fn == 0
        assert m.precision == 1.0
        assert m.recall == 1.0
        assert m.f1 == 1.0

    def test_benchmark_metrics_to_dict(self) -> None:
        m = BenchmarkMetrics(
            precision=0.8,
            recall=0.6,
            f1=0.685,
            tp=4,
            fp=1,
            fn=2,
            high_risk_fp_rate=0.2,
            effective_localization_rate=0.75,
            total_ground_truth=6,
            total_predictions=5,
            recall_at_k={5: 0.5},
            recall_at_k_values=[5, 10],
            matches=4,
        )
        d = m.to_dict()
        assert d["precision"] == 0.8
        assert d["tp"] == 4
        assert d["recall_at_k"][5] == 0.5

    def test_recall_at_k_uses_maximum_matching_for_each_prefix(self, tmp_path: Path) -> None:
        gt_path = tmp_path / "java.json"
        gt_path.write_text(
            """
            {
              "entries": [
                {
                  "id": "gt-1",
                  "language": "java",
                  "category": "security",
                  "relative_path": "src/A.java",
                  "cwe_id": "CWE-89",
                  "sink_line": 10,
                  "start_line": 1,
                  "end_line": 10,
                  "vulnerable": true
                },
                {
                  "id": "gt-2",
                  "language": "java",
                  "category": "security",
                  "relative_path": "src/A.java",
                  "cwe_id": "CWE-89",
                  "sink_line": 10,
                  "start_line": 1,
                  "end_line": 10,
                  "vulnerable": true
                }
              ]
            }
            """,
            encoding="utf-8",
        )
        runner = EvaluationRunner(str(tmp_path))

        class RankedPredictor:
            def predict(self, dataset_root: str, language: str) -> list[PredictionEntry]:
                return [
                    _make_pred(path="src/A.java", start=1, end=10),
                    _make_pred(path="src/A.java", start=1, end=10),
                ]

        result = runner.evaluate(
            RankedPredictor(),
            _DATASETS,
            "java",
            recall_at_k_values=[1, 2],
        )

        assert result.unmatched_pred_indices == ()
        assert result.metrics.recall_at_k == {1: 0.5, 2: 1.0}


# ── Ground truth file integrity ─────────────────────────────────────────────


class TestGroundTruthIntegrity:
    def test_all_ground_truth_paths_exist(self) -> None:
        """Every relative_path in ground truth must point to a real dataset file."""
        runner = EvaluationRunner(_GT_DIR)
        for lang in ("java", "python"):
            gt = runner.load_ground_truth(lang)
            for entry in gt:
                full = Path(_DATASETS) / ".." / entry.relative_path
                resolved = full.resolve()
                assert resolved.is_file(), f"Missing: {entry.relative_path}"

    def test_all_ground_truth_ids_are_unique(self) -> None:
        runner = EvaluationRunner(_GT_DIR)
        for lang in ("java", "python"):
            gt = runner.load_ground_truth(lang)
            ids = [e.id for e in gt]
            assert len(ids) == len(set(ids)), f"Duplicate IDs in {lang}"

    def test_vulnerable_and_safe_samples_exist(self) -> None:
        """Per §18.1, each category must have both vulnerable and safe samples."""
        for lang in ("java", "python"):
            ext = "*.java" if lang == "java" else "*.py"
            cat_dirs = sorted((Path(_DATASETS) / lang).iterdir())
            assert len(cat_dirs) >= 8, f"Expected ≥8 categories for {lang}"
            for cat_dir in cat_dirs:
                if not cat_dir.is_dir():
                    continue
                files = sorted(cat_dir.glob(ext))
                assert len(files) >= 2, (
                    f"{cat_dir.relative_to(_DATASETS)} should have ≥2 {lang} files "
                    f"(vulnerable + safe), found {len(files)}: {[f.name for f in files]}"
                )

    def test_assert_check_sink_points_to_assert_statement(self) -> None:
        runner = EvaluationRunner(_GT_DIR)
        entry = next(
            item
            for item in runner.load_ground_truth("python")
            if item.id == "python-assert-check-001"
        )
        source = (
            (Path(_DATASETS) / ".." / entry.relative_path)
            .resolve()
            .read_text(encoding="utf-8")
            .splitlines()
        )

        assert source[entry.sink_line - 1].lstrip().startswith("assert ")
