"""Tests for outreach ingest + job prefill merge."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
for entry in (str(_REPO_ROOT), str(_REPO_ROOT / "dashboard")):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from outreach_signal_prefill import merge_outreach_form_defaults  # noqa: E402


class OutreachSignalPrefillTests(unittest.TestCase):
    def test_ingest_fills_empty_fields(self) -> None:
        merged = merge_outreach_form_defaults(
            job_prefill={"person_name": "", "company": "Job Co"},
            ingest_draft={
                "person_name": "Alex",
                "company": "Post Co",
                "notes": "Hiring PM",
            },
        )
        self.assertEqual(merged["person_name"], "Alex")
        self.assertEqual(merged["company"], "Job Co")
        self.assertEqual(merged["notes"], "Hiring PM")

    def test_job_link_fields_preserved(self) -> None:
        merged = merge_outreach_form_defaults(
            job_prefill={
                "opportunity_id": "v2:test:1",
                "opportunity_url": "https://example.com/job",
                "company": "Acme",
            },
            ingest_draft={"company": "Other", "hiring_signal_url": "https://linkedin.com/posts/x"},
        )
        self.assertEqual(merged["opportunity_id"], "v2:test:1")
        self.assertEqual(merged["opportunity_url"], "https://example.com/job")
        self.assertEqual(merged["company"], "Acme")
        self.assertEqual(
            merged["hiring_signal_url"],
            "https://linkedin.com/posts/x",
        )


if __name__ == "__main__":
    unittest.main()
