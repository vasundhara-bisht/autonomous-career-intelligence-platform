"""Tests for lifecycle monitor dashboard polling and wake behaviour."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

_REPO_ROOT = Path(__file__).resolve().parent.parent
for entry in (str(_REPO_ROOT), str(_REPO_ROOT / "dashboard"), str(_REPO_ROOT / "src")):
    if entry not in sys.path:
        sys.path.insert(0, entry)


class MonitorUiPollingTests(unittest.TestCase):
    def test_monitor_ui_defines_running_detector_and_30s_fragment(self) -> None:
        source = (_REPO_ROOT / "dashboard" / "monitor_ui.py").read_text(encoding="utf-8")
        self.assertIn("def monitor_db_running", source)
        self.assertIn("OP_LIFECYCLE_POLL_WAKE", source)
        self.assertIn("OP_ACQUISITION_POLL_WAKE", source)
        self.assertIn("def mark_lifecycle_poll_wake", source)
        self.assertIn("def mark_acquisition_poll_wake", source)
        self.assertIn("@st.fragment(run_every=timedelta(seconds=30))", source)
        self.assertIn("def _render_monitor_health_live", source)
        self.assertIn("def _render_monitor_health_body", source)
        self.assertIn("_should_poll_monitor_health", source)
        self.assertNotIn("timedelta(seconds=2)", source)

    def test_render_section_uses_conditional_live_fragment(self) -> None:
        source = (_REPO_ROOT / "dashboard" / "monitor_ui.py").read_text(encoding="utf-8")
        self.assertIn("if _should_poll_monitor_health():", source)
        self.assertIn("_render_monitor_health_live(dashboard_df)", source)
        self.assertIn("_render_monitor_health_body(dashboard_df)", source)

    def test_monitor_db_running_queries_running_status(self) -> None:
        from monitor_ui import monitor_db_running

        mock_session = MagicMock()
        mock_session.execute.return_value.first.return_value = (1,)
        mock_cm = MagicMock()
        mock_cm.__enter__.return_value = mock_session
        mock_cm.__exit__.return_value = None

        with patch("monitor_ui.dashboard_read_enabled", return_value=True):
            with patch("db.bootstrap.ensure_database_ready"):
                with patch(
                    "db.read.engine.get_dashboard_read_session",
                    return_value=mock_cm,
                ):
                    self.assertTrue(monitor_db_running())
        sql = str(mock_session.execute.call_args[0][0])
        self.assertIn("status = 'running'", sql)

    def test_operator_controls_sets_lifecycle_wake_on_run_now(self) -> None:
        source = (
            _REPO_ROOT / "dashboard" / "operator_controls_ui.py"
        ).read_text(encoding="utf-8")
        self.assertIn("mark_lifecycle_poll_wake", source)
        self.assertIn("mark_acquisition_poll_wake", source)
        self.assertIn('if scheduler_key == "lifecycle":', source)
        self.assertIn('elif scheduler_key == "acquisition":', source)


class MonitorUiWakeHelperTests(unittest.TestCase):
    def test_lifecycle_poll_wake_expires(self) -> None:
        import monitor_ui as module

        session_state: dict[str, object] = {
            module.OP_LIFECYCLE_POLL_WAKE: True,
            module.OP_LIFECYCLE_POLL_WAKE_UNTIL: 0.0,
        }
        with patch.object(module, "st") as mock_st:
            mock_st.session_state = session_state
            self.assertFalse(module.lifecycle_poll_wake_active())
        self.assertNotIn(module.OP_LIFECYCLE_POLL_WAKE, session_state)

    def test_acquisition_poll_wake_expires(self) -> None:
        import monitor_ui as module

        session_state: dict[str, object] = {
            module.OP_ACQUISITION_POLL_WAKE: True,
            module.OP_ACQUISITION_POLL_WAKE_UNTIL: 0.0,
        }
        with patch.object(module, "st") as mock_st:
            mock_st.session_state = session_state
            self.assertFalse(module.acquisition_poll_wake_active())
        self.assertNotIn(module.OP_ACQUISITION_POLL_WAKE, session_state)


if __name__ == "__main__":
    unittest.main()
