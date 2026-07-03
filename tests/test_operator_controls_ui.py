"""Tests for scheduler status reader and operator controls UI (OHM Phase 5)."""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

_REPO_ROOT = Path(__file__).resolve().parent.parent
for entry in (str(_REPO_ROOT), str(_REPO_ROOT / "dashboard"), str(_REPO_ROOT / "src")):
    if entry not in sys.path:
        sys.path.insert(0, entry)


class SchedulerStatusReaderTests(unittest.TestCase):
    def test_read_scheduler_status_includes_gated_resume(self) -> None:
        import importlib.util

        module_path = _REPO_ROOT / "scripts/scheduling/read_scheduler_status.py"
        spec = importlib.util.spec_from_file_location("read_scheduler_status", module_path)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        payload = module.read_scheduler_status(repo_root=_REPO_ROOT)
        self.assertTrue(payload.get("lifecycle_resume_gated"))
        schedulers = payload.get("schedulers")
        self.assertIsInstance(schedulers, dict)
        assert isinstance(schedulers, dict)
        self.assertIn("acquisition", schedulers)
        self.assertIn("lifecycle", schedulers)
        lifecycle = schedulers["lifecycle"]
        self.assertEqual(lifecycle.get("next_run_estimate"), "~17:00 daily")

    def test_schedule_summary_for_acquisition(self) -> None:
        import importlib.util

        module_path = _REPO_ROOT / "scripts/scheduling/read_scheduler_status.py"
        spec = importlib.util.spec_from_file_location("read_scheduler_status", module_path)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        label = module._schedule_summary("acquisition", repo_root=_REPO_ROOT)
        self.assertEqual(label, "~09:00, 21:00 daily")

    def test_launchctl_not_loaded_state(self) -> None:
        import importlib.util
        from unittest.mock import patch

        module_path = _REPO_ROOT / "scripts/scheduling/read_scheduler_status.py"
        spec = importlib.util.spec_from_file_location("read_scheduler_status", module_path)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        with patch.object(module, "_launchctl_print", return_value=(False, "Could not find service")):
            entry = module.read_scheduler_entry("lifecycle", label="com.example.lifecycle")
        self.assertFalse(entry["launchctl_loaded"])
        self.assertEqual(entry["launchctl_state"], "not_loaded")


class OperatorControlsUiTests(unittest.TestCase):
    def test_section_rendered_before_health_sections(self) -> None:
        source = (_REPO_ROOT / "dashboard" / "app.py").read_text(encoding="utf-8")
        controls_idx = source.rindex("render_operational_controls_section(")
        acquisition_idx = source.rindex("render_acquisition_health_section(")
        self.assertLess(controls_idx, acquisition_idx)

    def test_operator_controls_module_exists(self) -> None:
        source = (_REPO_ROOT / "dashboard" / "operator_controls_ui.py").read_text(encoding="utf-8")
        self.assertIn("render_operational_controls_section", source)
        self.assertIn('"Resume"', source)
        self.assertIn("lifecycle_resume_gated=lifecycle_gated", source)
        self.assertIn("Approve lifecycle re-enable", source)
        self.assertIn("_resume_lifecycle_scheduler", source)
        self.assertIn("op-status-badge", source)
        self.assertIn("Next scheduled run", source)
        self.assertIn("Paused by operator", source)
        self.assertNotIn("Label:", source)
        self.assertNotIn("Next run (template)", source)
        self.assertNotIn("Operator actions (local machine)", source)

    def test_operator_actions_always_rendered(self) -> None:
        source = (_REPO_ROOT / "dashboard" / "operator_controls_ui.py").read_text(encoding="utf-8")
        self.assertIn('"Pause"', source)
        self.assertIn('"Run now"', source)
        self.assertIn("disabled=not writes_enabled", source)
        self.assertIn("op-lock-hint", source)
        self.assertNotIn("Confirm run", source)
        self.assertIn("View Only mode", source)
        self.assertIn("st.dialog", source)
        self.assertIn("op-lock-hint-row", source)
        self.assertNotIn("op-run-now-slot", source)
        self.assertNotIn("op-resume-slot", source)
        self.assertNotIn("op-actions-row", source)

    def test_run_confirmation_copy(self) -> None:
        from operator_controls_ui import _run_confirmation_body, _run_confirmation_title

        self.assertEqual(_run_confirmation_title("Acquisition"), "Run acquisition now?")
        acq_body = _run_confirmation_body("Acquisition").lower()
        self.assertIn("manual acquisition run", acq_body)
        self.assertIn("operator pause does not block", acq_body)
        self.assertEqual(_run_confirmation_title("Lifecycle Monitor"), "Run lifecycle monitor now?")
        lifecycle_body = _run_confirmation_body("Lifecycle Monitor").lower()
        self.assertIn("manual lifecycle monitor run", lifecycle_body)
        self.assertIn("operator pause does not block", lifecycle_body)

    def test_execute_run_now_uses_manual_wrapper_not_kickstart(self) -> None:
        source = (_REPO_ROOT / "dashboard" / "operator_controls_ui.py").read_text(encoding="utf-8")
        self.assertIn("_execute_manual_run", source)
        self.assertIn("run_manual_acquisition.sh", source)
        self.assertIn("run_manual_lifecycle_monitor.sh", source)
        self.assertIn("subprocess.Popen", source)
        self.assertNotIn("_kickstart_scheduler", source)
        self.assertNotIn("launchctl kickstart", source)

    def test_execute_manual_run_launches_background_process(self) -> None:
        from unittest.mock import MagicMock

        from operator_controls_ui import _execute_manual_run

        mock_popen = MagicMock()
        with patch("operator_controls_ui.subprocess.Popen", mock_popen):
            ok, message = _execute_manual_run(scheduler_key="acquisition", title="Acquisition")
        self.assertTrue(ok)
        self.assertIn("logs/manual/acquisition-", message)
        mock_popen.assert_called_once()
        args, kwargs = mock_popen.call_args
        self.assertEqual(args[0][0], "bash")
        self.assertIn("run_manual_acquisition.sh", args[0][1])
        self.assertIn("ACQUISITION_RUN_LOG_FILE", kwargs["env"])
        self.assertTrue(kwargs.get("start_new_session"))

    def test_execute_run_now_sets_lifecycle_wake_flag(self) -> None:
        from operator_controls_ui import _execute_run_now
        import monitor_ui as monitor_module

        session_state: dict[str, object] = {}
        with patch("operator_controls_ui._execute_manual_run", return_value=(True, "started")):
            with patch("operator_controls_ui.st") as mock_controls_st:
                with patch.object(monitor_module, "st") as mock_monitor_st:
                    mock_controls_st.session_state = session_state
                    mock_monitor_st.session_state = session_state
                    _execute_run_now(scheduler_key="lifecycle", title="Lifecycle Monitor")
        self.assertTrue(session_state.get(monitor_module.OP_LIFECYCLE_POLL_WAKE))
        self.assertIn(monitor_module.OP_LIFECYCLE_POLL_WAKE_UNTIL, session_state)

    def test_execute_run_now_sets_acquisition_wake_flag(self) -> None:
        from operator_controls_ui import _execute_run_now
        import monitor_ui as monitor_module

        session_state: dict[str, object] = {}
        with patch("operator_controls_ui._execute_manual_run", return_value=(True, "started")):
            with patch("operator_controls_ui.st") as mock_controls_st:
                with patch.object(monitor_module, "st") as mock_monitor_st:
                    mock_controls_st.session_state = session_state
                    mock_monitor_st.session_state = session_state
                    _execute_run_now(scheduler_key="acquisition", title="Acquisition")
        self.assertTrue(session_state.get(monitor_module.OP_ACQUISITION_POLL_WAKE))
        self.assertIn(monitor_module.OP_ACQUISITION_POLL_WAKE_UNTIL, session_state)

    def test_format_next_scheduled_run(self) -> None:
        from operator_controls_ui import _format_next_scheduled_run

        self.assertEqual(_format_next_scheduled_run("~09:00, 21:00 daily"), "09:00 & 21:00 daily")
        self.assertEqual(_format_next_scheduled_run("~17:00 daily"), "5:00 PM daily")

    def test_scheduler_status_badge_labels(self) -> None:
        from operator_controls_ui import _scheduler_status_badge

        self.assertEqual(
            _scheduler_status_badge({"operator_paused": True, "launchctl_state": "running"}),
            ("Paused by operator", "yellow"),
        )
        self.assertEqual(
            _scheduler_status_badge(
                {"operator_paused": False, "launchctl_state": "running", "plist_installed": True}
            ),
            ("Scheduled", "green"),
        )
        self.assertEqual(
            _scheduler_status_badge(
                {"operator_paused": False, "launchctl_state": "unknown", "plist_installed": True}
            ),
            ("Scheduled", "green"),
        )
        self.assertEqual(
            _scheduler_status_badge(
                {"operator_paused": False, "launchctl_state": "not_loaded", "plist_installed": True}
            ),
            ("Not loaded", "red"),
        )

    def test_scheduler_badge_alias_matches_scheduler_status(self) -> None:
        from operator_controls_ui import _scheduler_badge, _scheduler_status_badge

        entry = {"operator_paused": False, "launchctl_state": "running", "plist_installed": True}
        self.assertEqual(_scheduler_badge(entry), _scheduler_status_badge(entry))

    def test_execution_status_badge(self) -> None:
        from operator_controls_ui import _execution_status_badge

        self.assertEqual(_execution_status_badge(running=True), ("Running", "green"))
        self.assertEqual(_execution_status_badge(running=False), ("Idle", "grey"))

    def test_scheduler_card_dual_status_rows(self) -> None:
        source = (_REPO_ROOT / "dashboard" / "operator_controls_ui.py").read_text(encoding="utf-8")
        self.assertIn('"Scheduler status"', source)
        self.assertIn("_scheduler_status_badge", source)
        self.assertIn("_execution_status_badge", source)
        self.assertIn("_scheduler_is_executing", source)
        self.assertIn("_operator_execution_poll_needed", source)
        self.assertIn("@st.fragment(run_every=timedelta(seconds=30))", source)
        self.assertIn("_render_operational_controls_live", source)

    def test_scheduler_badge_tones(self) -> None:
        from operator_controls_ui import _scheduler_badge

        self.assertEqual(_scheduler_badge({"operator_paused": True, "launchctl_state": "running"})[1], "yellow")
        self.assertEqual(_scheduler_badge({"operator_paused": False, "launchctl_state": "running", "plist_installed": True})[0], "Scheduled")
        self.assertEqual(_scheduler_badge({"operator_paused": False, "launchctl_state": "not_loaded", "plist_installed": True})[1], "red")

    def test_ai_refresh_card_present(self) -> None:
        source = (_REPO_ROOT / "dashboard" / "operator_controls_ui.py").read_text(encoding="utf-8")
        self.assertIn("_render_ai_refresh_card", source)
        self.assertIn("Refresh AI Evaluations", source)
        self.assertIn("_execute_ai_refresh_run", source)
        self.assertIn("op_run_ai_refresh", source)
        self.assertIn("Current status", source)
        self.assertIn("_format_ai_refresh_last_run_summary", source)
        self.assertNotIn("op-actions-label", source)
        self.assertNotIn("Trigger", source)
        self.assertIn("_ai_refresh_is_running", source)
        self.assertIn("refresh_col, _ = st.columns(2)", source)
        self.assertNotIn("c1, c2, c3 = st.columns(3)", source)

    def test_ai_refresh_status_badge(self) -> None:
        from operator_controls_ui import _ai_refresh_status_badge

        self.assertEqual(_ai_refresh_status_badge(True), ("Running", "green"))
        self.assertEqual(_ai_refresh_status_badge(False), ("Not Running", "grey"))

    def test_format_ai_refresh_last_run_summary_no_runs(self) -> None:
        from operator_controls_ui import _format_ai_refresh_last_run_summary

        rows = _format_ai_refresh_last_run_summary(None, preset_labels={"backlog": "Refresh Evaluations"})
        self.assertEqual(rows, [("Last completed run", "No runs yet")])

    def test_format_ai_refresh_last_run_summary_uses_timestamp(self) -> None:
        from datetime import datetime

        from operator_controls_ui import _format_ai_refresh_last_run_summary

        last_run = {
            "run_id": 7,
            "completed_at": datetime(2026, 6, 27, 17, 56, 0),
            "preset": "backlog",
            "scored_count": 284,
            "persist_skipped_count": 0,
            "batch_failures": 0,
        }
        rows = _format_ai_refresh_last_run_summary(
            last_run,
            preset_labels={"backlog": "Refresh Evaluations"},
        )
        self.assertEqual(rows[0][0], "Last completed run")
        self.assertIn("Jun 2026", rows[0][1])
        self.assertEqual(rows[1], ("Preset", "Refresh Evaluations"))
        self.assertEqual(rows[2], ("Jobs scored", "284"))

    def test_format_ai_refresh_last_run_summary_fallback_run_id(self) -> None:
        from operator_controls_ui import _format_ai_refresh_last_run_summary

        last_run = {
            "run_id": 12,
            "completed_at": None,
            "preset": "backlog",
            "scored_count": 5,
        }
        rows = _format_ai_refresh_last_run_summary(
            last_run,
            preset_labels={"backlog": "Refresh Evaluations"},
        )
        self.assertEqual(rows[0], ("Last completed run", "Run 12"))

    def test_format_ai_refresh_last_run_summary_optional_counts(self) -> None:
        from operator_controls_ui import _format_ai_refresh_last_run_summary

        last_run = {
            "run_id": 3,
            "completed_at": "2026-06-27T12:00:00",
            "preset": "backlog",
            "scored_count": 10,
            "persist_skipped_count": 2,
            "batch_failures": 1,
        }
        rows = _format_ai_refresh_last_run_summary(
            last_run,
            preset_labels={"backlog": "Refresh Evaluations"},
        )
        labels = [label for label, _ in rows]
        self.assertIn("Persist skipped", labels)
        self.assertIn("Batch failures", labels)

    def test_main_py_uses_orchestrator(self) -> None:
        source = (_REPO_ROOT / "src/agent/main.py").read_text(encoding="utf-8")
        self.assertIn("run_batch_ai_scoring", source)
        self.assertNotIn("batch_score_jobs", source)

    def test_write_gate_follows_dashboard_write_enabled(self) -> None:
        from db.read.engine import dashboard_write_enabled

        source = (_REPO_ROOT / "dashboard" / "operator_controls_ui.py").read_text(encoding="utf-8")
        self.assertNotIn("DASHBOARD_OPERATOR_CONTROLS", source)
        self.assertNotIn("operator_controls_write_enabled", source)
        self.assertIn("writes_enabled = dashboard_write_enabled()", source)

        with patch.dict(
            os.environ,
            {"SQLITE_ENABLED": "1", "SQLITE_READ": "1", "SQLITE_DASHBOARD_WRITE": "1"},
            clear=False,
        ):
            self.assertTrue(dashboard_write_enabled())
        with patch.dict(
            os.environ,
            {"SQLITE_ENABLED": "1", "SQLITE_READ": "1", "SQLITE_DASHBOARD_WRITE": "0"},
            clear=False,
        ):
            self.assertFalse(dashboard_write_enabled())


class MonitorSummaryParserTests(unittest.TestCase):
    def test_parse_provider_summary_and_deferrals(self) -> None:
        from db.read.monitor_summary import deferral_counts, parse_provider_summary

        summary = (
            "linkedin_skipped_auth=3,protection_reason=protection:unusual_activity,"
            "auth_probe_reason=auth:ok"
        )
        parsed = parse_provider_summary(summary)
        self.assertEqual(parsed["auth_probe_reason"], "auth:ok")
        counts = deferral_counts(summary)
        self.assertEqual(counts["linkedin_skipped_auth"], 3)


if __name__ == "__main__":
    unittest.main()
