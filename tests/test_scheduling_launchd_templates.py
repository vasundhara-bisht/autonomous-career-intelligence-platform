"""Launchd plist template schedule assertions (Task 3 / TD1)."""

from __future__ import annotations

import plistlib
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_LAUNCHD_DIR = _REPO_ROOT / "scripts" / "scheduling" / "launchd"


def _calendar_hours(template_name: str) -> list[int]:
    path = _LAUNCHD_DIR / template_name
    with path.open("rb") as handle:
        payload = plistlib.load(handle)
    intervals = payload.get("StartCalendarInterval")
    if isinstance(intervals, dict):
        intervals = [intervals]
    if not isinstance(intervals, list):
        raise AssertionError(f"{template_name}: expected StartCalendarInterval array or dict")
    hours: list[int] = []
    for entry in intervals:
        if not isinstance(entry, dict):
            continue
        hour = entry.get("Hour")
        if isinstance(hour, int):
            hours.append(hour)
    return sorted(hours)


class SchedulingLaunchdTemplateTests(unittest.TestCase):
    def test_acquisition_schedule_td1(self) -> None:
        self.assertEqual(
            _calendar_hours("com.vasundhara-bisht.ai-job-agent.acquisition.plist.template"),
            [9, 21],
        )

    def test_lifecycle_monitor_schedule_ohm_phase1(self) -> None:
        self.assertEqual(
            _calendar_hours("com.vasundhara-bisht.ai-job-agent.lifecycle-monitor.plist.template"),
            [17],
        )

    def test_install_script_references_lifecycle_template(self) -> None:
        install_sh = (_REPO_ROOT / "scripts" / "scheduling" / "install_launchagents.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("lifecycle-monitor.plist.template", install_sh)
        self.assertIn("run_dashboard.sh", install_sh)

    def test_uninstall_script_references_lifecycle_agent(self) -> None:
        uninstall_sh = (
            _REPO_ROOT / "scripts" / "scheduling" / "uninstall_launchagents.sh"
        ).read_text(encoding="utf-8")
        self.assertIn("com.vasundhara-bisht.ai-job-agent.lifecycle-monitor", uninstall_sh)
        self.assertIn("ai-job-agent-lifecycle-monitor.lock", uninstall_sh)


if __name__ == "__main__":
    unittest.main()
