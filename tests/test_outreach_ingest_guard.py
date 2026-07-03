"""Tests for outreach ingest guards."""

from __future__ import annotations

import sys
import unittest
from datetime import datetime
from pathlib import Path

import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parent.parent
for entry in (str(_REPO_ROOT), str(_REPO_ROOT / "dashboard"), str(_REPO_ROOT / "src")):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from outreach_ingest_guard import (  # noqa: E402
    SAVE_SUCCESS_MESSAGE,
    clear_duplicate_hiring_signal,
    consume_outreach_save_success,
    duplicate_hiring_signal_warning_lines,
    find_existing_outreach_by_hiring_signal_url,
    get_duplicate_hiring_signal,
    normalize_hiring_signal_url_for_match,
    request_open_existing_outreach_record,
    request_outreach_save_success,
    should_fetch_hiring_signal_details,
    store_duplicate_hiring_signal,
)

_SAMPLE_POST = (
    "https://www.linkedin.com/posts/jane-founder_hiring-pm-activity-123"
)
_SAMPLE_POST_WITH_UTM = (
    "https://www.linkedin.com/posts/jane-founder_hiring-pm-activity-123"
    "?utm_source=share"
)


def _sample_outreach_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "id": 7,
                "person_name": "Jane Founder",
                "company": "Acme Fintech",
                "status": "sent",
                "hiring_signal_url": _SAMPLE_POST,
                "created_at": datetime(2026, 6, 10, 12, 0, 0),
            }
        ]
    )


class OutreachIngestGuardTests(unittest.TestCase):
    def test_normalize_hiring_signal_url_strips_query_params(self) -> None:
        left = normalize_hiring_signal_url_for_match(_SAMPLE_POST)
        right = normalize_hiring_signal_url_for_match(_SAMPLE_POST_WITH_UTM)
        self.assertEqual(left, right)

    def test_find_existing_outreach_detects_duplicate_before_enrichment(self) -> None:
        match = find_existing_outreach_by_hiring_signal_url(
            _sample_outreach_df(),
            _SAMPLE_POST_WITH_UTM,
        )
        self.assertIsNotNone(match)
        self.assertEqual(match["id"], 7)
        self.assertEqual(match["person_name"], "Jane Founder")

    def test_find_existing_outreach_returns_none_for_new_url(self) -> None:
        match = find_existing_outreach_by_hiring_signal_url(
            _sample_outreach_df(),
            "https://www.linkedin.com/posts/other-user_hiring-activity-999",
        )
        self.assertIsNone(match)

    def test_duplicate_warning_includes_existing_metadata(self) -> None:
        record = _sample_outreach_df().iloc[0].to_dict()
        lines = duplicate_hiring_signal_warning_lines(record)
        self.assertEqual(lines[0], "This hiring signal already exists.")
        self.assertIn("Jane Founder", lines[1])
        self.assertIn("Acme Fintech", lines[2])
        self.assertIn("Sent", lines[3])
        self.assertIn("10-06-2026", lines[4])

    def test_save_success_message_pending_survives_rerun_once(self) -> None:
        state: dict[str, object] = {}
        request_outreach_save_success(state)
        self.assertTrue(state["outreach_save_success_pending"])

        self.assertTrue(consume_outreach_save_success(state))
        self.assertEqual(SAVE_SUCCESS_MESSAGE, "✓ Outreach saved successfully")
        self.assertFalse(state["outreach_save_success_pending"])
        self.assertFalse(consume_outreach_save_success(state))

    def test_duplicate_record_stored_and_cleared(self) -> None:
        state: dict[str, object] = {}
        record = _sample_outreach_df().iloc[0].to_dict()
        store_duplicate_hiring_signal(state, record)
        stored = get_duplicate_hiring_signal(state)
        self.assertIsNotNone(stored)
        self.assertEqual(stored["id"], 7)
        clear_duplicate_hiring_signal(state)
        self.assertIsNone(get_duplicate_hiring_signal(state))

    def test_should_fetch_hiring_signal_details(self) -> None:
        self.assertFalse(
            should_fetch_hiring_signal_details(_sample_outreach_df(), _SAMPLE_POST_WITH_UTM)
        )
        self.assertTrue(
            should_fetch_hiring_signal_details(
                _sample_outreach_df(),
                "https://www.linkedin.com/posts/other-user_hiring-activity-999",
            )
        )

    def test_open_existing_record_sets_focus_and_clears_duplicate(self) -> None:
        state: dict[str, object] = {}
        store_duplicate_hiring_signal(state, _sample_outreach_df().iloc[0].to_dict())
        request_open_existing_outreach_record(state, 7)
        self.assertEqual(state["outreach_focus_record_id"], 7)
        self.assertIsNone(get_duplicate_hiring_signal(state))


if __name__ == "__main__":
    unittest.main()
