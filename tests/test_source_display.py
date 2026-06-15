"""Tests for source display-name mapping (display layer only)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_DASHBOARD = Path(__file__).resolve().parent.parent / "dashboard"
if str(_DASHBOARD) not in sys.path:
    sys.path.insert(0, str(_DASHBOARD))

from source_display import source_display_name  # noqa: E402


class SourceDisplayTests(unittest.TestCase):
    def test_known_sources(self) -> None:
        self.assertEqual(source_display_name("linkedin"), "LinkedIn")
        self.assertEqual(source_display_name("instahyre"), "InstaHyre")
        self.assertEqual(source_display_name("lever"), "Lever")
        self.assertEqual(source_display_name("greenhouse"), "Greenhouse")
        self.assertEqual(source_display_name("weworkremotely"), "WeWorkRemotely")

    def test_case_insensitive(self) -> None:
        self.assertEqual(source_display_name("LinkedIn"), "LinkedIn")

    def test_unknown_passthrough(self) -> None:
        self.assertEqual(source_display_name("custom_board"), "custom_board")

    def test_empty(self) -> None:
        self.assertEqual(source_display_name(""), "")
        self.assertEqual(source_display_name(None), "")


if __name__ == "__main__":
    unittest.main()
