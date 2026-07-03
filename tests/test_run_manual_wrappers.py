"""Source-scan tests for manual vs scheduled scheduling wrappers."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCHEDULING = _REPO_ROOT / "scripts" / "scheduling"


class ManualWrapperScriptTests(unittest.TestCase):
    def test_manual_wrappers_exist_and_skip_pause_check(self) -> None:
        for name in ("run_manual_acquisition.sh", "run_manual_lifecycle_monitor.sh"):
            path = _SCHEDULING / name
            self.assertTrue(path.is_file(), msg=f"missing {name}")
            source = path.read_text(encoding="utf-8")
            self.assertNotIn("check_operator_pause.py", source)
            self.assertIn("logs/manual", source)

    def test_manual_wrappers_export_trigger_env(self) -> None:
        acq = (_SCHEDULING / "run_manual_acquisition.sh").read_text(encoding="utf-8")
        lifecycle = (_SCHEDULING / "run_manual_lifecycle_monitor.sh").read_text(encoding="utf-8")
        self.assertIn("ACQUISITION_RUN_TRIGGER=manual", acq)
        self.assertIn("LIFECYCLE_MONITOR_RUN_TRIGGER=manual", lifecycle)

    def test_scheduled_wrappers_still_call_pause_check_and_export_trigger(self) -> None:
        acq = (_SCHEDULING / "run_scheduled_acquisition.sh").read_text(encoding="utf-8")
        lifecycle = (_SCHEDULING / "run_scheduled_lifecycle_monitor.sh").read_text(encoding="utf-8")
        self.assertIn("check_operator_pause.py", acq)
        self.assertIn("check_operator_pause.py", lifecycle)
        self.assertIn("ACQUISITION_RUN_TRIGGER=scheduled", acq)
        self.assertIn("LIFECYCLE_MONITOR_RUN_TRIGGER=scheduled", lifecycle)
        self.assertIn("logs/scheduled", acq)
        self.assertIn("logs/scheduled", lifecycle)


if __name__ == "__main__":
    unittest.main()
