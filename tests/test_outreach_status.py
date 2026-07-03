"""Tests for outreach status normalization."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
for entry in (str(_REPO_ROOT), str(_REPO_ROOT / "dashboard")):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from outreach_status import (  # noqa: E402
    ACTIVE_OUTREACH_STATUSES,
    HIRING_SIGNAL_TYPES,
    normalize_hiring_signal_type,
    normalize_outreach_status,
    hiring_signal_label,
    outreach_status_label,
)


class OutreachStatusTests(unittest.TestCase):
    def test_unknown_status_defaults_to_planned(self) -> None:
        self.assertEqual(normalize_outreach_status(None), "planned")
        self.assertEqual(normalize_outreach_status("bogus"), "planned")

    def test_label_mapping(self) -> None:
        self.assertEqual(outreach_status_label("referral_offered"), "Referral Offered")
        self.assertEqual(outreach_status_label("meeting_scheduled"), "Meeting Scheduled")

    def test_active_status_set(self) -> None:
        self.assertIn("sent", ACTIVE_OUTREACH_STATUSES)
        self.assertIn("referral_offered", ACTIVE_OUTREACH_STATUSES)
        self.assertNotIn("planned", ACTIVE_OUTREACH_STATUSES)
        self.assertNotIn("closed", ACTIVE_OUTREACH_STATUSES)

    def test_hiring_signal_normalization(self) -> None:
        self.assertEqual(normalize_hiring_signal_type(None), "")
        self.assertEqual(normalize_hiring_signal_type("Mentor Referral"), "mentor_referral")
        self.assertEqual(normalize_hiring_signal_type("personal_referral"), "personal_referral")
        self.assertNotEqual(
            normalize_hiring_signal_type("Mentor Referral"),
            normalize_hiring_signal_type("Personal Referral"),
        )
        self.assertEqual(normalize_hiring_signal_type("bogus signal"), "other")

    def test_hiring_signal_labels(self) -> None:
        for signal in HIRING_SIGNAL_TYPES:
            self.assertTrue(hiring_signal_label(signal))
        self.assertEqual(hiring_signal_label("mentor_referral"), "Mentor Referral")
        self.assertEqual(hiring_signal_label(""), "Not set")


if __name__ == "__main__":
    unittest.main()
