"""Tests for temporary LinkedIn classifier diagnostics."""

from __future__ import annotations

import io
import os
import sys
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
for entry in (str(_REPO_ROOT), str(_SRC)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

_FIXTURES = Path(__file__).resolve().parent / "fixtures"
_VALID_URL = "https://www.linkedin.com/jobs/view/4417376197/"


def _load_fixture(name: str) -> str:
    return (_FIXTURES / name).read_text(encoding="utf-8")


class LinkedInClassifierDiagnosticsTests(unittest.TestCase):
    def test_error_shell_with_closure_reports_failing_live_shell(self) -> None:
        from monitor.classifiers.linkedin import classify_linkedin_page
        from monitor.classifiers.linkedin_diagnostics import (
            build_linkedin_classifier_diagnostic_report,
        )

        html = _load_fixture("linkedin_job_error_shell_with_closure.html")
        classification = classify_linkedin_page(url=_VALID_URL, html=html)
        report = build_linkedin_classifier_diagnostic_report(
            job_key_v2="v2:linkedin:test",
            url=_VALID_URL,
            html=html,
            http_status=200,
            classification=classification,
        )
        self.assertFalse(report.signals["live_shell"])
        self.assertIsNotNone(report.signals["closed_phrase"])
        self.assertIn("removed:error_shell_with_closure", report.format())

    def test_flagship3_no_h1_closed_reports_live_shell_true(self) -> None:
        from monitor.classifiers.linkedin import classify_linkedin_page
        from monitor.classifiers.linkedin_diagnostics import (
            build_linkedin_classifier_diagnostic_report,
        )

        html = _load_fixture("linkedin_job_closed_flagship3_no_h1.html")
        classification = classify_linkedin_page(
            url="https://www.linkedin.com/jobs/view/4416317709/",
            html=html,
        )
        report = build_linkedin_classifier_diagnostic_report(
            job_key_v2="v2:linkedin:4416317709",
            url="https://www.linkedin.com/jobs/view/4416317709/",
            html=html,
            http_status=200,
            classification=classification,
        )
        self.assertTrue(report.signals["has_job_title"])
        self.assertTrue(report.signals["live_shell"])
        self.assertIn("closed:phrase:no_longer_accepting_applications", report.format())

    def test_flagship3_closed_reports_live_shell_true(self) -> None:
        from monitor.classifiers.linkedin import classify_linkedin_page
        from monitor.classifiers.linkedin_diagnostics import (
            build_linkedin_classifier_diagnostic_report,
        )

        html = _load_fixture("linkedin_job_closed_flagship3.html")
        classification = classify_linkedin_page(
            url="https://www.linkedin.com/jobs/view/4409792769/",
            html=html,
        )
        report = build_linkedin_classifier_diagnostic_report(
            url="https://www.linkedin.com/jobs/view/4409792769/",
            html=html,
            http_status=200,
            classification=classification,
        )
        self.assertTrue(report.signals["live_shell"])
        self.assertTrue(report.signals["has_flagship3_shell_metadata"])
        self.assertIn("closed:phrase:", report.format())

    def test_emit_writes_to_stderr(self) -> None:
        from monitor.classifiers.linkedin import classify_linkedin_page
        from monitor.classifiers.linkedin_diagnostics import (
            emit_linkedin_classifier_diagnostic_report,
        )

        html = _load_fixture("linkedin_job_closed_flagship3.html")
        classification = classify_linkedin_page(
            url="https://www.linkedin.com/jobs/view/4409792769/",
            html=html,
        )
        buffer = io.StringIO()
        with redirect_stderr(buffer):
            emit_linkedin_classifier_diagnostic_report(
                job_key_v2="v2:linkedin:4409792769",
                url="https://www.linkedin.com/jobs/view/4409792769/",
                html=html,
                http_status=200,
                classification=classification,
            )
        output = buffer.getvalue()
        self.assertIn("LINKEDIN CLASSIFIER DEBUG", output)
        self.assertIn("live_shell: True", output)
        self.assertIn("decision path", output.lower())

    def test_debug_enabled_env_var(self) -> None:
        from monitor.classifiers.linkedin_diagnostics import linkedin_classifier_debug_enabled

        with mock.patch.dict(os.environ, {"LIFECYCLE_MONITOR_LINKEDIN_CLASSIFIER_DEBUG": "1"}):
            self.assertTrue(linkedin_classifier_debug_enabled())
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertFalse(linkedin_classifier_debug_enabled())


if __name__ == "__main__":
    unittest.main()
