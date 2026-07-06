"""Reproducible benchmark and ablation experiment runner.

The checked-in manifest uses deterministic fixture predictions so CI can verify
the complete evaluation path without paid API calls. Formal model runs can use
the same schema with exported prediction snapshots and measured telemetry.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from benchmark.predictors.fake_predictor import FakePredictor
from benchmark.runner import EvaluationRunner, PredictionEntry

_METRIC_NAMES = (
    "precision",
    "recall",
    "f1",
    "high_risk_fp_rate",
    "effective_localization_rate",
)


@dataclass(frozen=True, slots=True)
class Variant:
    """One ablation variant backed by a versioned prediction snapshot."""

    name: str
    description: str
    include_fingerprints: dict[str, frozenset[str]]


class SelectedPredictionPredictor:
    """Select a stable subset from an exported prediction snapshot."""

    def __init__(
        self,
        prediction_dir: Path,
        include_fingerprints: dict[str, frozenset[str]],
    ) -> None:
        self._source = FakePredictor(str(prediction_dir))
        self._include = include_fingerprints

    def predict(self, dataset_root: str, language: str) -> list[PredictionEntry]:
        allowed = self._include.get(language, frozenset())
        predictions = self._source.predict(dataset_root, language)
        return [prediction for prediction in predictions if prediction.fingerprint in allowed]


def _load_manifest(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("manifest root must be an object")
    data: dict[str, Any] = raw
    if data.get("schema_version") != 1:
        raise ValueError("manifest schema_version must be 1")
    repetitions = data.get("repetitions")
    if not isinstance(repetitions, int) or not 3 <= repetitions <= 5:
        raise ValueError("manifest repetitions must be between 3 and 5")
    groups = data.get("groups")
    if not isinstance(groups, list) or not groups:
        raise ValueError("manifest groups must be a non-empty list")
    return data


def _parse_variant(raw: dict[str, Any], languages: tuple[str, ...]) -> Variant:
    selections = raw.get("include_fingerprints")
    if not isinstance(selections, dict):
        raise ValueError("variant include_fingerprints must be an object")
    include: dict[str, frozenset[str]] = {}
    for language in languages:
        fingerprints = selections.get(language)
        if not isinstance(fingerprints, list) or not all(
            isinstance(value, str) and value for value in fingerprints
        ):
            raise ValueError(f"variant must select fingerprints for {language}")
        if len(fingerprints) != len(set(fingerprints)):
            raise ValueError(f"variant contains duplicate {language} fingerprints")
        include[language] = frozenset(fingerprints)
    return Variant(
        name=str(raw["name"]),
        description=str(raw["description"]),
        include_fingerprints=include,
    )


def _summarize(values: list[float]) -> dict[str, float]:
    return {
        "mean": statistics.fmean(values),
        "std": statistics.pstdev(values),
    }


def _summarize_telemetry(
    raw: object,
    languages: tuple[str, ...],
    repetitions: int,
    unavailable_reason: str,
) -> dict[str, Any]:
    if raw is None:
        return {
            "status": "unavailable",
            "mean_latency_ms": None,
            "p95_latency_ms": None,
            "mean_input_tokens": None,
            "mean_output_tokens": None,
            "mean_estimated_cost": None,
            "currency": None,
            "pricing_version": None,
            "reason": unavailable_reason,
        }
    if not isinstance(raw, dict):
        raise ValueError("variant telemetry must be an object")

    trials: list[dict[str, Any]] = []
    for language in languages:
        language_trials = raw.get(language)
        if not isinstance(language_trials, list) or len(language_trials) != repetitions:
            raise ValueError(f"telemetry must contain {repetitions} {language} trials")
        if not all(isinstance(trial, dict) for trial in language_trials):
            raise ValueError(f"all {language} telemetry trials must be objects")
        trials.extend(language_trials)

    required = {
        "latency_ms",
        "input_tokens",
        "output_tokens",
        "estimated_cost",
        "currency",
        "pricing_version",
    }
    if any(not required.issubset(trial) for trial in trials):
        raise ValueError("telemetry trial is missing required fields")
    currencies = {str(trial["currency"]) for trial in trials}
    pricing_versions = {str(trial["pricing_version"]) for trial in trials}
    if len(currencies) != 1 or len(pricing_versions) != 1:
        raise ValueError("telemetry must use one currency and pricing version")

    latencies = [int(trial["latency_ms"]) for trial in trials]
    input_tokens = [int(trial["input_tokens"]) for trial in trials]
    output_tokens = [int(trial["output_tokens"]) for trial in trials]
    costs = [Decimal(str(trial["estimated_cost"])) for trial in trials]
    numeric_counts = [*latencies, *input_tokens, *output_tokens]
    if any(value < 0 for value in numeric_counts) or any(cost < 0 for cost in costs):
        raise ValueError("telemetry values must be non-negative")
    p95_index = max(0, math.ceil(len(latencies) * 0.95) - 1)

    return {
        "status": "available",
        "mean_latency_ms": statistics.fmean(latencies),
        "p95_latency_ms": sorted(latencies)[p95_index],
        "mean_input_tokens": statistics.fmean(input_tokens),
        "mean_output_tokens": statistics.fmean(output_tokens),
        "mean_estimated_cost": str(sum(costs, Decimal("0")) / len(costs)),
        "currency": currencies.pop(),
        "pricing_version": pricing_versions.pop(),
        "reason": None,
    }


def run_experiments(manifest_path: Path) -> dict[str, Any]:
    """Run every manifest variant and return deterministic aggregate results."""
    manifest = _load_manifest(manifest_path)
    root = manifest_path.parent
    languages = tuple(manifest["languages"])
    repetitions = manifest["repetitions"]
    runner = EvaluationRunner(str(root / manifest["ground_truth_dir"]))
    dataset_root = str(root / manifest["dataset_dir"])
    prediction_dir = root / manifest["prediction_dir"]

    groups: list[dict[str, Any]] = []
    seen_variant_names: set[str] = set()
    for raw_group in manifest["groups"]:
        variants: list[dict[str, Any]] = []
        for raw_variant in raw_group["variants"]:
            variant = _parse_variant(raw_variant, languages)
            if variant.name in seen_variant_names:
                raise ValueError(f"duplicate variant name: {variant.name}")
            seen_variant_names.add(variant.name)
            predictor = SelectedPredictionPredictor(
                prediction_dir,
                variant.include_fingerprints,
            )

            language_results: dict[str, Any] = {}
            runs_by_language: dict[str, list[Any]] = {}
            for language in languages:
                runs = [
                    runner.evaluate(predictor, dataset_root, language).metrics
                    for _ in range(repetitions)
                ]
                runs_by_language[language] = runs
                language_results[language] = {
                    "counts": {
                        "tp": runs[0].tp,
                        "fp": runs[0].fp,
                        "fn": runs[0].fn,
                    },
                    "metrics": {
                        metric_name: _summarize([float(getattr(run, metric_name)) for run in runs])
                        for metric_name in _METRIC_NAMES
                    },
                    "recall_at_k": {
                        str(k): _summarize([run.recall_at_k[k] for run in runs])
                        for k in runs[0].recall_at_k
                    },
                }

            macro_metrics = {
                metric_name: _summarize(
                    [
                        statistics.fmean(
                            float(getattr(runs_by_language[language][run_index], metric_name))
                            for language in languages
                        )
                        for run_index in range(repetitions)
                    ]
                )
                for metric_name in _METRIC_NAMES
            }
            variants.append(
                {
                    "name": variant.name,
                    "description": variant.description,
                    "languages": language_results,
                    "macro_metrics": macro_metrics,
                    "telemetry": _summarize_telemetry(
                        raw_variant.get("telemetry"),
                        languages,
                        repetitions,
                        manifest["telemetry_unavailable_reason"],
                    ),
                }
            )
        groups.append(
            {
                "id": raw_group["id"],
                "title": raw_group["title"],
                "variants": variants,
            }
        )

    manifest_bytes = manifest_path.read_bytes()
    return {
        "schema_version": 1,
        "benchmark_kind": manifest["benchmark_kind"],
        "disclaimer": manifest["disclaimer"],
        "dataset_version": manifest["dataset_version"],
        "prediction_snapshot_version": manifest["prediction_snapshot_version"],
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "repetitions": repetitions,
        "fixed_parameters": manifest["fixed_parameters"],
        "groups": groups,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path(__file__).with_name("ablation_manifest.json"),
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    result = run_experiments(args.manifest.resolve())
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output is None:
        print(rendered, end="")
        return
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8")


if __name__ == "__main__":
    main()
