from __future__ import annotations

import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "src"))

from agent.ai_batch_scorer import (  # noqa: E402
    normalize_ai_batch_response,
    validate_ai_batch_results,
)


class AIBatchNormalizationTests(unittest.TestCase):
    def test_single_item_dict_response(self) -> None:
        parsed = {"index": 0, "score": 8, "reason": "Strong PM fit"}
        normalized, meta = normalize_ai_batch_response(parsed)
        self.assertEqual(len(normalized), 1)
        self.assertEqual(meta["normalization_strategy_used"], "single_dict_wrapped")

        valid, skipped = validate_ai_batch_results(normalized, batch_size=1)
        self.assertEqual(len(valid), 1)
        self.assertEqual(skipped, 0)
        self.assertEqual(valid[0]["index"], 0)

    def test_wrapped_results_response(self) -> None:
        parsed = {
            "results": [
                {"index": 0, "score": 9, "reason": "Great fit"},
                {"index": 1, "score": 7, "reason": "Good fit"},
            ]
        }
        normalized, meta = normalize_ai_batch_response(parsed)
        self.assertEqual(len(normalized), 2)
        self.assertEqual(meta["normalization_strategy_used"], "wrapped_results_list")

        valid, skipped = validate_ai_batch_results(normalized, batch_size=2)
        self.assertEqual(len(valid), 2)
        self.assertEqual(skipped, 0)

    def test_malformed_response(self) -> None:
        parsed = {"foo": "bar"}
        normalized, meta = normalize_ai_batch_response(parsed)
        self.assertEqual(normalized, [])
        self.assertEqual(meta["normalization_strategy_used"], "dict_unrecognized")

        valid, skipped = validate_ai_batch_results(normalized, batch_size=3)
        self.assertEqual(valid, [])
        self.assertEqual(skipped, 0)

    def test_empty_response(self) -> None:
        normalized, meta = normalize_ai_batch_response(None)
        self.assertEqual(normalized, [])
        self.assertEqual(meta["normalization_strategy_used"], "empty_none")

    def test_mixed_valid_invalid_entries(self) -> None:
        normalized = [
            {"index": 0, "score": 8, "reason": "Valid one"},
            {"index": "bad", "score": 6, "reason": "Invalid index"},
            {"index": 1, "score": "NaN", "reason": "Invalid score"},
            {"index": 2, "score": 7},
            "index",
        ]
        valid, skipped = validate_ai_batch_results(normalized, batch_size=3)
        self.assertEqual(len(valid), 1)
        self.assertEqual(skipped, 4)
        self.assertEqual(valid[0]["index"], 0)


if __name__ == "__main__":
    unittest.main()
