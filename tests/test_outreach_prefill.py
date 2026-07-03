"""Tests for job-linked outreach prefill."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parent.parent
for entry in (str(_REPO_ROOT), str(_REPO_ROOT / "dashboard")):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from outreach_prefill import build_job_prefill_options, prefill_for_job_label  # noqa: E402


class OutreachPrefillTests(unittest.TestCase):
    def test_empty_editor_df(self) -> None:
        options = build_job_prefill_options(pd.DataFrame())
        self.assertEqual(options, [("None", {})])

    def test_job_row_prefill_skips_invalid_hm(self) -> None:
        editor_df = pd.DataFrame(
            [
                {
                    "JOB_KEY_V2": "v2:test:co:1",
                    "Title": "PM",
                    "Company": "Co",
                    "Hiring Manager": "Not Specified",
                    "Link": "https://example.com/job",
                }
            ]
        )
        options = build_job_prefill_options(editor_df)
        self.assertEqual(len(options), 2)
        label, prefill = options[1]
        self.assertIn("PM", label)
        self.assertEqual(prefill["company"], "Co")
        self.assertEqual(prefill["opportunity_id"], "v2:test:co:1")
        self.assertEqual(prefill["person_name"], "")

    def test_prefill_for_job_label(self) -> None:
        editor_df = pd.DataFrame(
            [
                {
                    "JOB_KEY_V2": "v2:test:co:2",
                    "Title": "Eng",
                    "Company": "Acme",
                    "Hiring Manager": "Alex Lee",
                    "Link": "https://example.com/eng",
                }
            ]
        )
        prefill = prefill_for_job_label(editor_df, "Eng @ Acme")
        self.assertEqual(prefill["person_name"], "Alex Lee")
        self.assertEqual(prefill["opportunity_url"], "https://example.com/eng")

    def test_job_options_sorted_by_posted_date_descending(self) -> None:
        editor_df = pd.DataFrame(
            [
                {
                    "JOB_KEY_V2": "v2:old",
                    "Title": "Old Role",
                    "Company": "Co",
                    "Posted": "14-06-2026",
                    "Link": "https://example.com/old",
                },
                {
                    "JOB_KEY_V2": "v2:new",
                    "Title": "New Role",
                    "Company": "Co",
                    "Posted": "16-06-2026",
                    "Link": "https://example.com/new",
                },
                {
                    "JOB_KEY_V2": "v2:mid",
                    "Title": "Mid Role",
                    "Company": "Co",
                    "Posted": "15-06-2026",
                    "Link": "https://example.com/mid",
                },
                {
                    "JOB_KEY_V2": "v2:blank",
                    "Title": "Blank Date",
                    "Company": "Co",
                    "Posted": "",
                    "Link": "https://example.com/blank",
                },
            ]
        )
        options = build_job_prefill_options(editor_df)
        labels = [label for label, _ in options[1:]]
        self.assertEqual(
            labels,
            [
                "New Role @ Co — (16-06-2026)",
                "Mid Role @ Co — (15-06-2026)",
                "Old Role @ Co — (14-06-2026)",
                "Blank Date @ Co",
            ],
        )


if __name__ == "__main__":
    unittest.main()
