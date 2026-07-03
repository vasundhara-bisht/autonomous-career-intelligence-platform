"""Tests for closed-listing read-only job table helpers."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import pandas as pd
import streamlit as st

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DASHBOARD = _REPO_ROOT / "dashboard"
for entry in (str(_REPO_ROOT), str(_DASHBOARD)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from job_listings_editor import (  # noqa: E402
    CLOSED_LISTINGS_SECTION_TITLE,
    CLOSED_LISTING_READONLY_HELP,
    closed_listing_mask,
    closed_listings_readonly_column_config,
    filter_persisted_job_states,
    partition_editor_df_by_listing,
    style_closed_listings_display_df,
)


class ClosedListingMaskTests(unittest.TestCase):
    def test_detects_closed_from_listing_status(self) -> None:
        df = pd.DataFrame(
            [
                {"JOB_KEY": "a", "listing_status": "open"},
                {"JOB_KEY": "b", "listing_status": "closed"},
            ]
        )
        mask = closed_listing_mask(df)
        self.assertEqual(mask.tolist(), [False, True])

    def test_detects_closed_from_listing_badge(self) -> None:
        df = pd.DataFrame(
            [
                {"JOB_KEY": "a", "Listing": "Open"},
                {"JOB_KEY": "b", "Listing": "Closed"},
            ]
        )
        mask = closed_listing_mask(df)
        self.assertEqual(mask.tolist(), [False, True])

    def test_detects_closed_from_legacy_read_only_label(self) -> None:
        df = pd.DataFrame(
            [{"JOB_KEY": "b", "Listing": "Closed · read-only"}]
        )
        mask = closed_listing_mask(df)
        self.assertTrue(bool(mask.iloc[0]))


class PartitionEditorDfTests(unittest.TestCase):
    def test_partitions_open_and_closed_rows(self) -> None:
        editor_df = pd.DataFrame(
            [
                {"JOB_KEY": "open", "listing_status": "open", "Status": "New", "#": 1},
                {"JOB_KEY": "closed", "listing_status": "closed", "Status": "Saved", "#": 2},
            ]
        )
        open_df, closed_df = partition_editor_df_by_listing(
            editor_df,
            listing_visibility_enabled=True,
        )
        self.assertEqual(len(open_df), 1)
        self.assertEqual(open_df.iloc[0]["JOB_KEY"], "open")
        self.assertEqual(open_df.iloc[0]["#"], 1)
        self.assertEqual(len(closed_df), 1)
        self.assertEqual(closed_df.iloc[0]["JOB_KEY"], "closed")
        self.assertEqual(closed_df.iloc[0]["#"], 1)

    def test_returns_all_rows_when_visibility_disabled(self) -> None:
        editor_df = pd.DataFrame(
            [{"JOB_KEY": "closed", "listing_status": "closed", "Status": "Saved"}]
        )
        open_df, closed_df = partition_editor_df_by_listing(
            editor_df,
            listing_visibility_enabled=False,
        )
        self.assertEqual(len(open_df), 1)
        self.assertTrue(closed_df.empty)


class ReadonlyColumnConfigTests(unittest.TestCase):
    def test_status_and_notes_are_readonly_text(self) -> None:
        config = closed_listings_readonly_column_config(
            {
                "Status": st.column_config.SelectboxColumn("Status", options=["New"]),
                "Notes": st.column_config.TextColumn("Notes"),
                "Link": st.column_config.LinkColumn("Link"),
            }
        )
        self.assertEqual(config["Status"]["type_config"]["type"], "text")
        self.assertTrue(config["Status"].get("disabled"))
        self.assertEqual(config["Notes"]["type_config"]["type"], "text")
        self.assertTrue(config["Notes"].get("disabled"))
        self.assertEqual(config["Link"]["type_config"]["type"], "link")
        self.assertFalse(config["Link"].get("disabled", False))


class PersistFilterTests(unittest.TestCase):
    def test_filters_closed_job_states(self) -> None:
        editor_df = pd.DataFrame(
            [
                {"JOB_KEY": "open", "listing_status": "open"},
                {"JOB_KEY": "closed", "listing_status": "closed"},
            ]
        )
        states = [
            {"JOB_KEY": "open", "pipeline_stage": "New"},
            {"JOB_KEY": "closed", "pipeline_stage": "Applied"},
        ]
        filtered = filter_persisted_job_states(
            states,
            editor_df,
            listing_visibility_enabled=True,
        )
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["JOB_KEY"], "open")

    def test_leaves_states_when_visibility_disabled(self) -> None:
        editor_df = pd.DataFrame([{"JOB_KEY": "closed", "listing_status": "closed"}])
        states = [{"JOB_KEY": "closed", "pipeline_stage": "Applied"}]
        filtered = filter_persisted_job_states(
            states,
            editor_df,
            listing_visibility_enabled=False,
        )
        self.assertEqual(filtered, states)


class ClosedListingStyleTests(unittest.TestCase):
    def test_styler_applies_muted_background(self) -> None:
        df = pd.DataFrame([{"Title": "PM", "Listing": "Closed"}])
        css = style_closed_listings_display_df(df).to_html()
        self.assertIn("background-color: #f3f4f6", css)
        self.assertIn("color: #6b7280", css)


class ClosedListingSectionTests(unittest.TestCase):
    def test_section_title(self) -> None:
        self.assertEqual(CLOSED_LISTINGS_SECTION_TITLE, "Closed Listings (Read-only History)")

    def test_help_text_mentions_read_only(self) -> None:
        self.assertIn("read-only", CLOSED_LISTING_READONLY_HELP.lower())


if __name__ == "__main__":
    unittest.main()
