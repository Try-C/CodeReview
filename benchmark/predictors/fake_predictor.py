"""Fake prediction baseline — loads pre-built predictions from JSON files.

Used to verify the evaluation harness without requiring an LLM-based agent.
Each fake prediction file contains a deliberately imperfect set of predictions
so we can confirm Precision/Recall/F1 calculation in tests.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from benchmark.runner import PredictionEntry

logger = logging.getLogger(__name__)


class FakePredictor:
    """A Predictor that reads predictions from a JSON file on disk.

    The JSON file path is resolved as:
        <predictions_dir>/<language>.json

    If no file exists for the given language the predictor returns an empty
    list, simulating a silent no-op.
    """

    def __init__(self, predictions_dir: str) -> None:
        self._dir = Path(predictions_dir)

    # Satisfy the Predictor protocol.
    def predict(self, dataset_root: str, language: str) -> list[PredictionEntry]:
        """Load fake predictions for *language*."""
        path = self._dir / f"{language}.json"
        if not path.is_file():
            logger.warning("FakePredictor: no prediction file at %s", path)
            return []
        data = json.loads(path.read_text(encoding="utf-8"))
        entries = data.get("predictions", data) if isinstance(data, dict) else data
        return [PredictionEntry.from_dict(e) for e in entries]
