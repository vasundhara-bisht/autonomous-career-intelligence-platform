"""Tests for lifecycle monitor budget-exhausted skip status."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
for entry in (str(_REPO_ROOT), str(_SRC)):
    if entry not in sys.path:
        sys.path.insert(0, entry)


def _base_report(**overrides):
    from db.services.lifecycle_monitor import MonitorRunReport

    report = MonitorRunReport(mode="apply")
    report.auth_health = "ok"
    report.cohort_size = 0
    report.checked_count = 0
    report.check_failed_count = 0
    report.linkedin_skipped_limit = 5
    report.budget_exhausted_skip_eligible = True
    for key, value in overrides.items():
        setattr(report, key, value)
    return report


class MonitorRunStatusTests(unittest.TestCase):
    def test_should_mark_budget_exhausted_skip_when_eligible(self) -> None:
        from db.services.lifecycle_monitor import should_mark_budget_exhausted_skip

        report = _base_report()
        self.assertTrue(
            should_mark_budget_exhausted_skip(
                report,
                pre_governance_candidate_count=10,
                budget_exhausted_skip_eligible=True,
            )
        )

    def test_should_not_mark_when_no_candidates(self) -> None:
        from db.services.lifecycle_monitor import should_mark_budget_exhausted_skip

        report = _base_report()
        self.assertFalse(
            should_mark_budget_exhausted_skip(
                report,
                pre_governance_candidate_count=0,
                budget_exhausted_skip_eligible=True,
            )
        )

    def test_should_not_mark_when_work_performed(self) -> None:
        from db.services.lifecycle_monitor import should_mark_budget_exhausted_skip

        report = _base_report(checked_count=1, cohort_size=1)
        self.assertFalse(
            should_mark_budget_exhausted_skip(
                report,
                pre_governance_candidate_count=10,
                budget_exhausted_skip_eligible=True,
            )
        )

    def test_should_not_mark_when_auth_degraded(self) -> None:
        from db.services.lifecycle_monitor import should_mark_budget_exhausted_skip

        report = _base_report(auth_health="degraded")
        self.assertFalse(
            should_mark_budget_exhausted_skip(
                report,
                pre_governance_candidate_count=10,
                budget_exhausted_skip_eligible=True,
            )
        )

    def test_should_not_mark_when_protection_skip(self) -> None:
        from db.services.lifecycle_monitor import should_mark_budget_exhausted_skip

        report = _base_report(linkedin_skipped_protection=1)
        self.assertFalse(
            should_mark_budget_exhausted_skip(
                report,
                pre_governance_candidate_count=10,
                budget_exhausted_skip_eligible=True,
            )
        )

    def test_should_not_mark_when_error_summary_set(self) -> None:
        from db.services.lifecycle_monitor import should_mark_budget_exhausted_skip

        report = _base_report(error_summary="RuntimeError: boom")
        self.assertFalse(
            should_mark_budget_exhausted_skip(
                report,
                pre_governance_candidate_count=10,
                budget_exhausted_skip_eligible=True,
            )
        )

    def test_should_not_mark_when_not_budget_eligible(self) -> None:
        from db.services.lifecycle_monitor import should_mark_budget_exhausted_skip

        report = _base_report(budget_exhausted_skip_eligible=False)
        self.assertFalse(
            should_mark_budget_exhausted_skip(
                report,
                pre_governance_candidate_count=10,
                budget_exhausted_skip_eligible=False,
            )
        )


if __name__ == "__main__":
    unittest.main()
