"""Tests for the showcase/ excerpts only.

The private repository's real test suite (140+ files covering the
proprietary scoring, dedup, and acquisition behavior) is not published here.
This file exists purely to demonstrate that the showcase excerpts are
covered by tests, not to replicate that suite.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "showcase"))
sys.path.insert(0, str(_REPO_ROOT / "src"))

from acquisition_adapter_example import JobRecord, fetch_sample_jobs, normalize_record  # noqa: E402
from db.app_mode import AppMode, set_active_mode  # noqa: E402
from demo_policy_example import (  # noqa: E402
    automation_allowed,
    external_api_allowed,
    interactive_demo_writes_allowed,
)


class AcquisitionAdapterExampleTests(unittest.TestCase):
    def test_normalize_record_trims_and_shapes_fields(self) -> None:
        raw = {
            "id": "sample-001",
            "title": "  Senior Product Manager ",
            "company_name": " Example Robotics Co ",
            "location": "Remote",
            "url": "https://example.com/careers/sample-001",
            "posted": "3 days ago",
        }
        record = normalize_record(raw)
        self.assertEqual(
            record,
            JobRecord(
                source_id="sample-001",
                title="Senior Product Manager",
                company="Example Robotics Co",
                location="Remote",
                url="https://example.com/careers/sample-001",
                raw_posted_label="3 days ago",
            ),
        )

    def test_normalize_record_defaults_missing_location(self) -> None:
        raw = {
            "id": "sample-003",
            "title": "Product Manager",
            "company_name": "Example Co",
            "url": "https://example.com/careers/sample-003",
        }
        record = normalize_record(raw)
        self.assertEqual(record.location, "Unspecified")

    def test_fetch_sample_jobs_yields_normalized_records(self) -> None:
        records = list(fetch_sample_jobs())
        self.assertEqual(len(records), 2)
        self.assertTrue(all(isinstance(r, JobRecord) for r in records))


class DemoPolicyExampleTests(unittest.TestCase):
    def test_live_mode_allows_automation_and_external_apis(self) -> None:
        set_active_mode(AppMode.LIVE)
        self.assertTrue(automation_allowed())
        self.assertTrue(external_api_allowed())
        self.assertFalse(interactive_demo_writes_allowed())

    def test_demo_mode_denies_automation_and_external_apis(self) -> None:
        set_active_mode(AppMode.DEMO)
        self.assertFalse(automation_allowed())
        self.assertFalse(external_api_allowed())
        self.assertTrue(interactive_demo_writes_allowed())
        set_active_mode(AppMode.LIVE)  # reset for test isolation


if __name__ == "__main__":
    unittest.main()
