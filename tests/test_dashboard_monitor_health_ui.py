"""Dashboard layout tests for Operational Monitor Health section."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
for entry in (str(_REPO_ROOT), str(_REPO_ROOT / "dashboard")):
    if entry not in sys.path:
        sys.path.insert(0, entry)


class OperationalMonitorHealthLayoutTests(unittest.TestCase):
    def test_section_render_call_after_outreach_intelligence(self) -> None:
        source = (_REPO_ROOT / "dashboard" / "app.py").read_text(encoding="utf-8")
        outreach_idx = source.rindex("render_outreach_intelligence_section(")
        monitor_idx = source.rindex("render_operational_monitor_health_section(")
        self.assertGreater(monitor_idx, outreach_idx)

    def test_section_not_rendered_near_dashboard_header(self) -> None:
        source = (_REPO_ROOT / "dashboard" / "app.py").read_text(encoding="utf-8")
        header_metrics_idx = source.index('col3.metric("Total Recruiters"')
        after_header = source[header_metrics_idx : header_metrics_idx + 400]
        self.assertNotIn("render_operational_monitor_health_section(", after_header)

    def test_section_lives_in_monitor_ui_module(self) -> None:
        app_source = (_REPO_ROOT / "dashboard" / "app.py").read_text(encoding="utf-8")
        monitor_source = (_REPO_ROOT / "dashboard" / "monitor_ui.py").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "from monitor_ui import render_operational_monitor_health_section",
            app_source,
        )
        self.assertIn('render_subheader_with_help(\n        "Operational Monitor Health",', monitor_source)
        self.assertIn("Overall Login Status", monitor_source)
        self.assertNotIn('st.expander("Monitor run snapshot"', monitor_source)
        self.assertNotIn('st.expander("Monitor run snapshot"', app_source)

    def test_monitor_ui_renders_overall_health_banner_and_provider_cards(self) -> None:
        source = (_REPO_ROOT / "dashboard" / "monitor_ui.py").read_text(encoding="utf-8")
        self.assertIn("_render_badge_metric(k1", source)
        self.assertIn('"Overall Monitor Status"', source)
        self.assertIn('"Overall Login Status"', source)
        self.assertIn('"Overall Failure Rate"', source)
        self.assertIn('"Alerts"', source)
        self.assertIn("_render_status_banner", source)
        self.assertIn('render_subsection_heading("Provider Health")', source)
        self.assertIn("Jobs Needing Attention", source)
        self.assertIn("Paused Jobs", source)
        self.assertIn("monitor_pause_threshold", source)
        self.assertNotIn("Jobs needing attention", source)
        self.assertNotIn("Paused — needs attention", source)
        self.assertNotIn("Authentication probe", source)
        self.assertNotIn("LinkedIn deferrals", source)
        self.assertNotIn("Backoff until", source)
        self.assertIn("classify_status_banner", source)
        self.assertIn("build_monitor_run_history_df", source)
        self.assertIn("st.dataframe(history_df", source)
        self.assertIn("mon-compact-metric-value", source)
        self.assertIn("st.container(border=True)", source)
        self.assertIn("Eligible Monitor Queue", source)
        self.assertNotIn("Availability", source)
        self.assertIn("_render_monitor_health_body", source)
        self.assertIn("_render_monitor_health_live", source)
        self.assertIn("timedelta(seconds=30)", source)

    def test_pause_tooltip_uses_dynamic_threshold(self) -> None:
        source = (_REPO_ROOT / "dashboard" / "monitor_ui.py").read_text(encoding="utf-8")
        self.assertIn("monitor_pause_threshold()", source)
        self.assertIn("f\"After {threshold} consecutive check failures", source)


class OperationalMonitorHealthHelpTests(unittest.TestCase):
    def test_section_help_is_operator_focused(self) -> None:
        source = (_REPO_ROOT / "dashboard" / "monitor_ui.py").read_text(encoding="utf-8")
        self.assertIn("How the daily listing monitor is performing.", source)
        self.assertNotIn("monitor_provider_state", source)


if __name__ == "__main__":
    unittest.main()
