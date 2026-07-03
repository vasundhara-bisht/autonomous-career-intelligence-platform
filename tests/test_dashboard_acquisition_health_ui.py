"""Dashboard layout tests for Acquisition Health section."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
for entry in (str(_REPO_ROOT), str(_REPO_ROOT / "dashboard")):
    if entry not in sys.path:
        sys.path.insert(0, entry)


class AcquisitionHealthLayoutTests(unittest.TestCase):
    def test_section_rendered_before_operational_monitor_health(self) -> None:
        source = (_REPO_ROOT / "dashboard" / "app.py").read_text(encoding="utf-8")
        acquisition_idx = source.rindex("render_acquisition_health_section(")
        monitor_idx = source.rindex("render_operational_monitor_health_section(")
        self.assertLess(acquisition_idx, monitor_idx)

    def test_section_lives_in_acquisition_ui_module(self) -> None:
        app_source = (_REPO_ROOT / "dashboard" / "app.py").read_text(encoding="utf-8")
        acquisition_source = (_REPO_ROOT / "dashboard" / "acquisition_ui.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("from acquisition_ui import render_acquisition_health_section", app_source)
        self.assertIn('render_subheader_with_help(\n        "Acquisition Health",', acquisition_source)
        self.assertNotIn("st.expander", acquisition_source)

    def test_acquisition_ui_renders_kpi_rows_and_history_table(self) -> None:
        source = (_REPO_ROOT / "dashboard" / "acquisition_ui.py").read_text(encoding="utf-8")
        self.assertIn('k1.metric("Acquisition Health"', source)
        self.assertIn('k8.metric("Last Run Duration"', source)
        self.assertIn("Sub-step", source)
        self.assertNotIn('"Type"', source)
        self.assertIn("InstaHyre Interested sync", source)
        self.assertIn("build_acquisition_run_history_df", source)
        self.assertIn("st.dataframe(history_df", source)

    def test_operational_controls_section_before_health_sections(self) -> None:
        source = (_REPO_ROOT / "dashboard" / "app.py").read_text(encoding="utf-8")
        controls_idx = source.rindex("render_operational_controls_section(")
        acquisition_idx = source.rindex("render_acquisition_health_section(")
        self.assertLess(controls_idx, acquisition_idx)


if __name__ == "__main__":
    unittest.main()
