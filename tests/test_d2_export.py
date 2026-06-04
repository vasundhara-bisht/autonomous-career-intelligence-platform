"""Tests for Phase D2 DB-backed jobs.csv export gating."""

from __future__ import annotations

import sys
import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch

import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
for entry in (str(_REPO_ROOT), str(_SRC)):
    if entry not in sys.path:
        sys.path.insert(0, entry)


def _sample_jobs() -> list[dict]:
    return [
        {
            "normalized_title": "ai product manager",
            "normalized_company": "acme",
            "JOB_KEY_V2": "v2:test:1",
            "identity_source": "instahyre_id",
            "title": "AI Product Manager",
            "company": "Acme",
            "location": "Bengaluru",
            "link": "https://example.com/job-1",
            "source": "linkedin",
            "time_posted": "1d",
            "applied": False,
            "hiring_manager": "Not Specified",
            "ai_score": 8.0,
            "ai_status": "scored",
            "linkedin_query_id": "q1",
            "linkedin_query_group": "g1",
            "linkedin_query_label": "label1",
            "linkedin_filter_profile": "fp1",
            "linkedin_query_role": "anchor",
            "linkedin_run_ts": "2026-01-01T00:00:00",
            "rejected": False,
            "reason": "fit",
        },
        {
            "normalized_title": "product manager",
            "normalized_company": "beta",
            "JOB_KEY_V2": "v2:test:2",
            "identity_source": "instahyre_id",
            "title": "Product Manager",
            "company": "Beta",
            "location": "Mumbai",
            "link": "https://example.com/job-2",
            "source": "instahyre",
            "time_posted": "2d",
            "applied": False,
            "hiring_manager": "Not Specified",
            "ai_score": 7.0,
            "ai_status": "scored",
            "instahyre_feed_id": "feed1",
            "instahyre_query_id": "feed1",
            "instahyre_query_label": "pm feed",
            "instahyre_run_ts": "2026-01-01T00:00:00",
            "rejected": False,
            "reason": "ok",
        },
    ]


class D2ExportTests(unittest.TestCase):
    def test_prepare_export_pending_masks_score(self) -> None:
        from agent.main import _prepare_jobs_export_df

        df = pd.DataFrame(
            [
                {
                    "normalized_title": "x",
                    "normalized_company": "y",
                    "title": "X",
                    "company": "Y",
                    "location": "Bengaluru",
                    "link": "https://example.com",
                    "time_posted": "1d",
                    "ai_status": "pending",
                    "ai_score": 9,
                }
            ]
        )
        out = _prepare_jobs_export_df(df)
        self.assertEqual(len(out), 1)
        self.assertTrue(pd.isna(out.iloc[0]["ai_score"]))
        self.assertEqual(out.iloc[0]["priority"], True)

    def test_db_export_metadata_parity_when_db_matches(self) -> None:
        from agent.main import _prepare_jobs_export_df, save_to_csv_via_db_export

        jobs = _sample_jobs()
        db_df = _prepare_jobs_export_df(pd.DataFrame(jobs))

        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            out_path = Path(f.name)

        try:
            with patch("agent.main.paths.jobs_csv", return_value=out_path):
                with patch("agent.main._d2_export_from_db_enabled", return_value=True):
                    with patch("agent.main.ensure_database_ready"):
                        with patch(
                            "agent.main.get_read_session", return_value=nullcontext(object())
                        ):
                            with patch(
                                "agent.main.load_current_jobs_export_source_df",
                                return_value=db_df,
                            ):
                                used_db = save_to_csv_via_db_export(jobs)
            self.assertTrue(used_db)
            out = pd.read_csv(out_path, dtype=str, keep_default_na=False)
            self.assertEqual(out.loc[0, "linkedin_query_id"], "q1")
            self.assertEqual(out.loc[1, "instahyre_feed_id"], "feed1")
        finally:
            out_path.unlink(missing_ok=True)

    def test_db_export_allows_metadata_warning_only(self) -> None:
        from agent.main import _prepare_jobs_export_df, save_to_csv_via_db_export

        jobs = _sample_jobs()
        db_df = _prepare_jobs_export_df(pd.DataFrame(jobs))
        for col in (
            "linkedin_query_id",
            "linkedin_query_group",
            "linkedin_query_label",
            "linkedin_filter_profile",
            "linkedin_query_role",
            "linkedin_run_ts",
            "instahyre_feed_id",
            "instahyre_query_id",
            "instahyre_query_label",
            "instahyre_run_ts",
        ):
            if col in db_df.columns:
                db_df[col] = ""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            out_path = Path(f.name)

        try:
            with patch("agent.main.paths.jobs_csv", return_value=out_path):
                with patch("agent.main._d2_export_from_db_enabled", return_value=True):
                    with patch("agent.main.ensure_database_ready"):
                        with patch(
                            "agent.main.get_read_session", return_value=nullcontext(object())
                        ):
                            with patch(
                                "agent.main.load_current_jobs_export_source_df",
                                return_value=db_df,
                            ):
                                used_db = save_to_csv_via_db_export(jobs)
            self.assertTrue(used_db)
            out = pd.read_csv(out_path)
            self.assertEqual(len(out), 2)
        finally:
            out_path.unlink(missing_ok=True)

    def test_hard_parity_rejected_bool_vs_db_int(self) -> None:
        from agent.main import _d2_hard_parity_check, _prepare_jobs_export_df

        legacy_df = _prepare_jobs_export_df(pd.DataFrame(_sample_jobs()))
        db_df = legacy_df.copy()
        db_df["rejected"] = 0

        self.assertEqual(_d2_hard_parity_check(legacy_df, db_df), [])

    def test_hard_parity_rejected_semantic_mismatch(self) -> None:
        from agent.main import _d2_hard_parity_check, _prepare_jobs_export_df

        legacy_df = _prepare_jobs_export_df(pd.DataFrame(_sample_jobs()))
        db_df = legacy_df.copy()
        db_df["rejected"] = db_df["rejected"].astype(int)
        db_df.iloc[0, db_df.columns.get_loc("rejected")] = 1

        errors = _d2_hard_parity_check(legacy_df, db_df)
        self.assertTrue(any("rejected mismatches" in e for e in errors))

    def test_db_export_hard_mismatch_falls_back_to_legacy(self) -> None:
        from agent.main import _prepare_jobs_export_df, save_to_csv_via_db_export

        jobs = _sample_jobs()
        db_df = _prepare_jobs_export_df(pd.DataFrame(jobs))
        db_df.loc[0, "title"] = "Changed Title"

        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            out_path = Path(f.name)

        try:
            with patch("agent.main.paths.jobs_csv", return_value=out_path):
                with patch("agent.main._d2_export_from_db_enabled", return_value=True):
                    with patch("agent.main.ensure_database_ready"):
                        with patch(
                            "agent.main.get_read_session", return_value=nullcontext(object())
                        ):
                            with patch(
                                "agent.main.load_current_jobs_export_source_df",
                                return_value=db_df,
                            ):
                                used_db = save_to_csv_via_db_export(jobs)
            self.assertFalse(used_db)
            out = pd.read_csv(out_path)
            self.assertIn("AI Product Manager", out["title"].tolist())
        finally:
            out_path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
