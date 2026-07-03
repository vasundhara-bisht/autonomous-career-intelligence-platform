"""Smoke tests for outreach UI helpers."""

from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parent.parent
for entry in (str(_REPO_ROOT), str(_REPO_ROOT / "dashboard"), str(_REPO_ROOT / "src")):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from outreach_ui import (  # noqa: E402
    _ADD_OUTREACH_EXPANDED_KEY,
    _FETCH_URL_INPUT_KEY,
    _FETCH_URL_STATE_KEY,
    _INGEST_DRAFT_KEY,
    _JOB_SELECT_KEY,
    _PROFILE_SNAPSHOT_KEY,
    _RECOMMENDED_MESSAGE_KEY,
    _RESET_PENDING_KEY,
    _build_editor_df,
    apply_pending_outreach_ingest_reset,
    close_add_outreach_expander,
    collect_outreach_table_edits,
    filter_outreach_df,
    open_add_outreach_expander,
    request_outreach_add_cancel,
    request_outreach_ingest_reset,
    reset_outreach_ingest_state,
    show_pending_outreach_save_toast,
)
from outreach_ingest_guard import (  # noqa: E402
    SAVE_SUCCESS_MESSAGE,
    consume_outreach_save_success,
    request_outreach_save_success,
)
from outreach_status import HIRING_SIGNAL_NOT_SET  # noqa: E402


class OutreachUiTests(unittest.TestCase):
    def test_filter_due_today(self) -> None:
        df = pd.DataFrame(
            [
                {"status": "sent", "follow_up_date": "2026-06-10", "hiring_signal_type": ""},
                {"status": "sent", "follow_up_date": "2026-06-11", "hiring_signal_type": ""},
            ]
        )
        filtered = filter_outreach_df(
            df,
            selected_statuses=["sent"],
            followup_filter="Due today",
            selected_signal_types=[],
            reference_date=date(2026, 6, 10),
        )
        self.assertEqual(len(filtered), 1)

    def test_filter_by_hiring_signal(self) -> None:
        df = pd.DataFrame(
            [
                {"status": "sent", "follow_up_date": "", "hiring_signal_type": "mentor_referral"},
                {"status": "sent", "follow_up_date": "", "hiring_signal_type": "recruiter_message"},
                {"status": "sent", "follow_up_date": "", "hiring_signal_type": ""},
            ]
        )
        filtered = filter_outreach_df(
            df,
            selected_statuses=["sent"],
            followup_filter="All",
            selected_signal_types=["mentor_referral"],
            reference_date=date(2026, 6, 10),
        )
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered.iloc[0]["hiring_signal_type"], "mentor_referral")

        not_set_only = filter_outreach_df(
            df,
            selected_statuses=["sent"],
            followup_filter="All",
            selected_signal_types=[HIRING_SIGNAL_NOT_SET],
            reference_date=date(2026, 6, 10),
        )
        self.assertEqual(len(not_set_only), 1)
        self.assertEqual(not_set_only.iloc[0]["hiring_signal_type"], "")

    def test_collect_table_edits(self) -> None:
        before = pd.DataFrame(
            [
                {
                    "id": 1,
                    "Outreach Status": "Sent",
                    "Follow-Up": "",
                    "Hiring Signal Notes": "",
                    "Date Contacted": "2026-06-01",
                    "Signal Type": "Recruiter Message",
                    "Hiring Signal URL": "",
                }
            ]
        )
        after = before.copy()
        after.loc[0, "Outreach Status"] = "Replied"
        after.loc[0, "Signal Type"] = "Mentor Referral"
        edits = collect_outreach_table_edits(before, after)
        self.assertEqual(len(edits), 1)
        self.assertEqual(edits[0]["status"], "replied")
        self.assertEqual(edits[0]["hiring_signal_type"], "mentor_referral")

    def test_build_editor_df_signal_labels(self) -> None:
        df = pd.DataFrame(
            [
                {
                    "id": 1,
                    "person_name": "Alex",
                    "company": "Acme",
                    "designation": "Engineering Manager",
                    "outreach_channel": "linkedin",
                    "hiring_signal_type": "mentor_referral",
                    "status": "meeting_scheduled",
                    "date_contacted": "2026-06-01",
                    "follow_up_date": "",
                    "notes": "",
                    "opportunity_id": "",
                    "opportunity_url": "",
                    "hiring_signal_url": "",
                }
            ]
        )
        editor = _build_editor_df(df, write_enabled=False)
        self.assertEqual(editor.iloc[0]["Designation"], "Engineering Manager")
        self.assertEqual(editor.iloc[0]["Signal Type"], "Mentor Referral")
        self.assertEqual(editor.iloc[0]["Outreach Status"], "Meeting Scheduled")
        self.assertNotIn("Channel", editor.columns)
        self.assertIn("Linked Job", editor.columns)
        self.assertEqual(
            list(editor.columns[:6]),
            ["id", "#", "Person", "Designation", "Company", "Signal Type"],
        )

        unset = _build_editor_df(
            df.assign(hiring_signal_type=""),
            write_enabled=False,
        )
        self.assertEqual(unset.iloc[0]["Signal Type"], "Not set")

    def test_reset_outreach_ingest_state_clears_fetch_url(self) -> None:
        state = {
            _INGEST_DRAFT_KEY: {"person_name": "Jane"},
            _FETCH_URL_STATE_KEY: "https://www.linkedin.com/posts/jane_hiring",
            _FETCH_URL_INPUT_KEY: "https://www.linkedin.com/posts/jane_hiring",
        }
        reset_outreach_ingest_state(state)
        self.assertEqual(state[_INGEST_DRAFT_KEY], {})
        self.assertEqual(state[_FETCH_URL_STATE_KEY], "")
        self.assertNotIn(_FETCH_URL_INPUT_KEY, state)

    def test_request_outreach_ingest_reset_sets_pending_flag_only(self) -> None:
        state = {
            _INGEST_DRAFT_KEY: {"person_name": "Jane"},
            _FETCH_URL_INPUT_KEY: "https://www.linkedin.com/posts/jane_hiring",
        }
        request_outreach_ingest_reset(state)
        self.assertTrue(state[_RESET_PENDING_KEY])
        self.assertEqual(state[_FETCH_URL_INPUT_KEY], "https://www.linkedin.com/posts/jane_hiring")
        self.assertEqual(state[_INGEST_DRAFT_KEY], {"person_name": "Jane"})

    def test_apply_pending_reset_clears_state_before_widget_lifecycle(self) -> None:
        state = {
            _RESET_PENDING_KEY: True,
            _INGEST_DRAFT_KEY: {"person_name": "Jane"},
            _FETCH_URL_STATE_KEY: "https://www.linkedin.com/posts/jane_hiring",
            _FETCH_URL_INPUT_KEY: "https://www.linkedin.com/posts/jane_hiring",
        }
        applied = apply_pending_outreach_ingest_reset(state)
        self.assertTrue(applied)
        self.assertFalse(state[_RESET_PENDING_KEY])
        self.assertEqual(state[_INGEST_DRAFT_KEY], {})
        self.assertEqual(state[_FETCH_URL_STATE_KEY], "")
        self.assertNotIn(_FETCH_URL_INPUT_KEY, state)

    def test_save_flow_pattern_request_then_apply_on_next_run(self) -> None:
        state = {
            _INGEST_DRAFT_KEY: {"person_name": "Jane", "company": "Acme"},
            _FETCH_URL_STATE_KEY: "https://www.linkedin.com/posts/jane_hiring",
            _FETCH_URL_INPUT_KEY: "https://www.linkedin.com/posts/jane_hiring",
        }

        request_outreach_ingest_reset(state)
        self.assertTrue(state[_RESET_PENDING_KEY])
        self.assertIn(_FETCH_URL_INPUT_KEY, state)

        apply_pending_outreach_ingest_reset(state)
        self.assertEqual(state[_INGEST_DRAFT_KEY], {})
        self.assertNotIn(_FETCH_URL_INPUT_KEY, state)

        if _FETCH_URL_INPUT_KEY not in state:
            state[_FETCH_URL_INPUT_KEY] = ""
        self.assertEqual(state[_FETCH_URL_INPUT_KEY], "")

    def test_open_and_close_add_outreach_expander(self) -> None:
        state: dict[str, object] = {}
        self.assertFalse(state.get(_ADD_OUTREACH_EXPANDED_KEY))
        open_add_outreach_expander(state)
        self.assertTrue(state[_ADD_OUTREACH_EXPANDED_KEY])
        close_add_outreach_expander(state)
        self.assertFalse(state[_ADD_OUTREACH_EXPANDED_KEY])

    def test_request_outreach_add_cancel_clears_ingest_and_collapses(self) -> None:
        from outreach_ingest_guard import (  # noqa: E402
            get_duplicate_hiring_signal,
            get_focus_outreach_record_id,
            store_duplicate_hiring_signal,
        )

        state = {
            _INGEST_DRAFT_KEY: {"person_name": "Jane"},
            _FETCH_URL_STATE_KEY: "https://www.linkedin.com/posts/jane_hiring",
            _FETCH_URL_INPUT_KEY: "https://www.linkedin.com/posts/jane_hiring",
            _ADD_OUTREACH_EXPANDED_KEY: True,
        }
        store_duplicate_hiring_signal(
            state,
            {
                "id": 1,
                "person_name": "Jane",
                "company": "Acme",
                "status": "sent",
                "created_at": "2026-06-01",
            },
        )
        state["outreach_focus_record_id"] = 5
        request_outreach_add_cancel(state)
        self.assertTrue(state[_RESET_PENDING_KEY])
        self.assertIsNone(get_duplicate_hiring_signal(state))
        self.assertIsNone(get_focus_outreach_record_id(state))
        self.assertFalse(state[_ADD_OUTREACH_EXPANDED_KEY])

    @patch("outreach_ui.st.toast")
    def test_show_pending_outreach_save_toast_once(self, mock_toast) -> None:
        state: dict[str, object] = {}
        request_outreach_save_success(state)
        show_pending_outreach_save_toast(state)
        mock_toast.assert_called_once_with(SAVE_SUCCESS_MESSAGE, icon="✅")
        show_pending_outreach_save_toast(state)
        mock_toast.assert_called_once()

    def test_save_success_and_reset_pattern(self) -> None:
        state: dict[str, object] = {
            _INGEST_DRAFT_KEY: {"person_name": "Jane"},
            _FETCH_URL_INPUT_KEY: "https://www.linkedin.com/posts/jane_hiring",
        }
        request_outreach_save_success(state)
        request_outreach_ingest_reset(state)

        self.assertTrue(consume_outreach_save_success(state))
        self.assertFalse(consume_outreach_save_success(state))

        apply_pending_outreach_ingest_reset(state)
        self.assertEqual(state[_INGEST_DRAFT_KEY], {})
        self.assertNotIn(_FETCH_URL_INPUT_KEY, state)

    def test_outreach_message_in_prefill_fields(self) -> None:
        from outreach_signal_prefill import _PREFILL_FIELDS  # noqa: E402

        self.assertIn("outreach_message", _PREFILL_FIELDS)

    def test_cancel_clears_recommended_message_and_profile_snapshot(self) -> None:
        state: dict[str, object] = {
            _INGEST_DRAFT_KEY: {"person_name": "Jane"},
            _FETCH_URL_STATE_KEY: "https://www.linkedin.com/posts/jane_hiring",
            _FETCH_URL_INPUT_KEY: "https://www.linkedin.com/posts/jane_hiring",
            _RECOMMENDED_MESSAGE_KEY: "Hey Jane, saw your post about hiring.",
            _PROFILE_SNAPSHOT_KEY: "8 years in SaaS.",
            _ADD_OUTREACH_EXPANDED_KEY: True,
        }
        request_outreach_add_cancel(state)
        # The pending-reset flag is set; apply it to actually clear keys.
        apply_pending_outreach_ingest_reset(state)
        self.assertNotIn(_RECOMMENDED_MESSAGE_KEY, state)
        self.assertNotIn(_PROFILE_SNAPSHOT_KEY, state)
        self.assertFalse(state[_ADD_OUTREACH_EXPANDED_KEY])

    def test_reset_clears_recommended_message_and_profile_snapshot(self) -> None:
        state: dict[str, object] = {
            _INGEST_DRAFT_KEY: {"person_name": "Jane"},
            _RECOMMENDED_MESSAGE_KEY: "Hey Jane.",
            _PROFILE_SNAPSHOT_KEY: "My profile.",
        }
        reset_outreach_ingest_state(state)
        self.assertNotIn(_RECOMMENDED_MESSAGE_KEY, state)
        self.assertNotIn(_PROFILE_SNAPSHOT_KEY, state)

    def test_reset_clears_job_outreach_selectbox(self) -> None:
        state: dict[str, object] = {
            _INGEST_DRAFT_KEY: {"person_name": "Jane", "outreach_type": "job_outreach"},
            _JOB_SELECT_KEY: "PM @ Acme — Remote (2026-06-16)",
            _RECOMMENDED_MESSAGE_KEY: "Hi Alex,",
        }
        reset_outreach_ingest_state(state)
        self.assertNotIn(_JOB_SELECT_KEY, state)
        self.assertNotIn(_RECOMMENDED_MESSAGE_KEY, state)


if __name__ == "__main__":
    unittest.main()
