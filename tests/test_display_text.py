"""Tests for dashboard display_text helpers."""

from __future__ import annotations

import sys
import unittest
from dataclasses import dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DASHBOARD = _REPO_ROOT / "dashboard"
for entry in (str(_REPO_ROOT), str(_DASHBOARD)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from display_text import (  # noqa: E402
    format_action_rationale,
    format_rationale_for_popover,
    is_valid_job_url,
    truncate_for_display,
)


@dataclass(frozen=True)
class _FakeAction:
    rationale: str
    full_rationale: str


class DisplayTextTests(unittest.TestCase):
    def test_truncate_for_display_short_text(self) -> None:
        display, truncated = truncate_for_display("hello", 80)
        self.assertEqual(display, "hello")
        self.assertFalse(truncated)

    def test_truncate_for_display_long_text(self) -> None:
        text = "a" * 100
        display, truncated = truncate_for_display(text, 80)
        self.assertTrue(truncated)
        self.assertLessEqual(len(display), 80)
        self.assertTrue(display.endswith("…"))

    def test_truncate_for_display_empty(self) -> None:
        display, truncated = truncate_for_display("", 80)
        self.assertEqual(display, "")
        self.assertFalse(truncated)

    def test_format_action_rationale(self) -> None:
        action = _FakeAction(
            rationale="short",
            full_rationale="short but complete narrative with full AI reason",
        )
        display, full = format_action_rationale(action)
        self.assertEqual(display, "short")
        self.assertIn("full AI reason", full)

    def test_is_valid_job_url_https(self) -> None:
        self.assertTrue(is_valid_job_url("https://www.linkedin.com/jobs/123"))

    def test_is_valid_job_url_http(self) -> None:
        self.assertTrue(is_valid_job_url("http://example.com/job"))

    def test_is_valid_job_url_rejects_empty(self) -> None:
        self.assertFalse(is_valid_job_url(""))
        self.assertFalse(is_valid_job_url(None))

    def test_is_valid_job_url_rejects_non_http(self) -> None:
        self.assertFalse(is_valid_job_url("ftp://example.com"))
        self.assertFalse(is_valid_job_url("not-a-url"))

    def test_format_rationale_for_popover_multiline(self) -> None:
        raw = (
            "AI score 9/10\n"
            "Discovered 7 days ago\n"
            "Stage: discovery (New or Saved)\n"
            "AI reason: Strong product leadership fit."
        )
        formatted = format_rationale_for_popover(raw)
        self.assertIn("**AI score:** 9/10", formatted)
        self.assertIn("**Discovered:** 7 days ago", formatted)
        self.assertIn("**Stage:** discovery (New or Saved)", formatted)
        self.assertIn("**AI reason:** Strong product leadership fit.", formatted)
        self.assertIn("\n\n", formatted)

    def test_format_rationale_for_popover_single_paragraph(self) -> None:
        raw = (
            "AI score 9/10 Discovered 7 days ago Stage: discovery (New or Saved) "
            "AI reason: Strong product leadership fit."
        )
        formatted = format_rationale_for_popover(raw)
        self.assertIn("**AI score:** 9/10", formatted)
        self.assertIn("**Discovered:** 7 days ago", formatted)
        self.assertIn("**Stage:** discovery (New or Saved)", formatted)
        self.assertIn("**AI reason:** Strong product leadership fit.", formatted)


if __name__ == "__main__":
    unittest.main()
