"""Tests for shared AI batch scoring orchestration."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
for entry in (str(_REPO_ROOT), str(_SRC)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from agent.ai_scoring_orchestrator import run_batch_ai_scoring  # noqa: E402


def _job(n: int) -> dict:
    return {
        "title": f"Role {n}",
        "company": "Co",
        "location": "Remote",
        "description": "x" * 250,
    }


class AiScoringOrchestratorTests(unittest.TestCase):
    def test_debug_limit_caps_queue(self) -> None:
        jobs = [_job(i) for i in range(5)]
        with patch.dict(os.environ, {"DEBUG_LIMIT": "2"}, clear=False):
            result = run_batch_ai_scoring(jobs, verbose=False)

        self.assertEqual(len(result.ai_scoring_jobs), 2)
        self.assertEqual(len(result.pending_ai_jobs), 3)
        self.assertEqual(result.stats.ai_skipped_by_cap, 3)
        self.assertEqual(result.pending_ai_jobs[0]["ai_status"], "skipped_by_cap")
        self.assertEqual(result.ai_scoring_jobs[0]["ai_status"], "pending")

    def test_batch_scoring_applies_results(self) -> None:
        jobs = [_job(1)]

        def fake_batch(batch, profile):
            return {
                "request_ok": True,
                "results": [
                    {"index": 0, "score": 8.0, "reason": "Strong fintech SaaS fit."}
                ],
                "parsed_result_count": 1,
                "normalization_strategy_used": "list_passthrough",
            }

        with patch.dict(os.environ, {"DEBUG_LIMIT": "10"}, clear=False):
            with patch(
                "agent.ai_scoring_orchestrator.batch_score_jobs",
                side_effect=fake_batch,
            ):
                with patch(
                    "agent.ai_scoring_orchestrator.load_candidate_profile",
                    return_value="profile",
                ):
                    result = run_batch_ai_scoring(jobs, verbose=False)

        self.assertEqual(result.ai_scoring_jobs[0]["ai_status"], "scored")
        self.assertEqual(result.ai_scoring_jobs[0]["score"], 8.0)
        self.assertEqual(result.stats.ai_results_applied, 1)

    def test_failed_batch_leaves_pending(self) -> None:
        jobs = [_job(1)]

        with patch.dict(os.environ, {"DEBUG_LIMIT": "10"}, clear=False):
            with patch(
                "agent.ai_scoring_orchestrator.batch_score_jobs",
                return_value={"request_ok": False, "results": []},
            ):
                with patch(
                    "agent.ai_scoring_orchestrator.load_candidate_profile",
                    return_value="profile",
                ):
                    result = run_batch_ai_scoring(jobs, verbose=False)

        self.assertEqual(result.ai_scoring_jobs[0]["ai_status"], "pending")
        self.assertEqual(result.stats.batch_failures, 1)
        self.assertEqual(result.stats.ai_results_applied, 0)


if __name__ == "__main__":
    unittest.main()
