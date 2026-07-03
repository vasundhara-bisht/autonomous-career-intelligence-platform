"""Tests for canonical dashboard launcher (scripts/run_dashboard.sh)."""

from __future__ import annotations

import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_RUN_DASHBOARD = _REPO_ROOT / "scripts" / "run_dashboard.sh"


class RunDashboardScriptTests(unittest.TestCase):
    def test_script_exists_and_sources_env(self) -> None:
        text = _RUN_DASHBOARD.read_text(encoding="utf-8")
        self.assertIn('source "$ROOT/.env"', text)
        self.assertIn("dashboard/app.py", text)
        self.assertTrue(_RUN_DASHBOARD.stat().st_mode & 0o111, "run_dashboard.sh should be executable")


if __name__ == "__main__":
    unittest.main()
