"""Tests for shared dashboard UI help and heading helpers."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
for entry in (str(_REPO_ROOT), str(_REPO_ROOT / "dashboard")):
    if entry not in sys.path:
        sys.path.insert(0, entry)


class UiHelpTests(unittest.TestCase):
    def test_normalize_section_title_uppercases_and_strips(self) -> None:
        from ui_help import normalize_section_title

        self.assertEqual(normalize_section_title("  Acquisition Health  "), "ACQUISITION HEALTH")
        self.assertEqual(normalize_section_title(""), "")


if __name__ == "__main__":
    unittest.main()
