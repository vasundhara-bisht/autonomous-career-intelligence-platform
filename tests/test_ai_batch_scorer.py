"""Tests for AI description prep before OpenAI scoring."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "src"))

from agent.ai_batch_scorer import (  # noqa: E402
    AI_DESCRIPTION_MAX_CHARS,
    AI_DESCRIPTION_MIN_CLEAN_CHARS,
    prepare_description_for_scoring,
)


class PrepareDescriptionForScoringTests(unittest.TestCase):
    def test_preserves_casing(self) -> None:
        raw = (
            "About Acme\nAbout the Role\nOwn B2B SaaS roadmap for AI/ML platform. "
            + "X" * AI_DESCRIPTION_MIN_CLEAN_CHARS
        )
        out = prepare_description_for_scoring(raw)
        self.assertIn("B2B SaaS", out)
        self.assertIn("AI/ML", out)
        self.assertNotIn("b2b saas", out)

    def test_section_marker_case_insensitive(self) -> None:
        raw = (
            "Company fluff. RESPONSIBILITIES: Ship fintech features. "
            + "Y" * AI_DESCRIPTION_MIN_CLEAN_CHARS
        )
        out = prepare_description_for_scoring(raw)
        self.assertTrue(out.startswith(" Ship fintech") or "Ship fintech" in out[:80])
        self.assertIn("fintech", out)

    def test_caps_at_max_chars(self) -> None:
        raw = "Z" * (AI_DESCRIPTION_MAX_CHARS + 500)
        out = prepare_description_for_scoring(raw)
        self.assertEqual(len(out), AI_DESCRIPTION_MAX_CHARS)

    def test_short_cleaned_falls_back_to_full_raw(self) -> None:
        raw = "About the Role\nToo short"
        out = prepare_description_for_scoring(raw)
        self.assertEqual(out, raw)

    def test_empty_description(self) -> None:
        self.assertEqual(prepare_description_for_scoring(""), "")


if __name__ == "__main__":
    unittest.main()
