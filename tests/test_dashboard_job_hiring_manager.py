"""Tests for dashboard Hiring Manager persist integration."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from sqlalchemy import select

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
_DASHBOARD = _REPO_ROOT / "dashboard"
for entry in (str(_REPO_ROOT), str(_SRC), str(_DASHBOARD)):
    if entry not in sys.path:
        sys.path.insert(0, entry)


def _clear_db_caches() -> None:
    from db.engine import get_engine, get_session_factory

    get_engine.cache_clear()
    get_session_factory.cache_clear()


class DashboardHiringManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._data = Path(self._tmpdir.name)
        self._env_patch = patch.dict(
            os.environ,
            {
                "AI_JOB_AGENT_DATA_DIR": str(self._data),
                "AI_JOB_AGENT_DB_PATH": str(self._data / "test.db"),
                "SQLITE_ENABLED": "1",
                "SQLITE_READ": "1",
                "SQLITE_DASHBOARD_WRITE": "1",
            },
            clear=False,
        )
        self._env_patch.start()
        _clear_db_caches()

    def tearDown(self) -> None:
        self._env_patch.stop()
        _clear_db_caches()
        self._tmpdir.cleanup()

    def _seed_job(self, *, v2: str = "v2:instahyre:co:888") -> None:
        from db.bootstrap import ensure_database_ready
        from db.engine import get_session
        from db.models.schema import Job, UserJobState

        ensure_database_ready()
        now = datetime.now(UTC).replace(tzinfo=None)
        with get_session() as session:
            job = Job(
                job_key="pm::co",
                job_key_v2=v2,
                title="PM",
                company="Co",
                source="instahyre",
                hiring_manager="Not Specified",
            )
            session.add(job)
            session.flush()
            session.add(
                UserJobState(
                    job_id=job.id,
                    applied=False,
                    rejected=False,
                    pipeline_stage="New",
                    updated_at=now,
                )
            )
            session.commit()

    def _editor_row(self, *, hm: str = "Not Specified") -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "#": 1,
                    "JOB_KEY": "pm::co",
                    "JOB_KEY_V2": "v2:instahyre:co:888",
                    "Title": "PM",
                    "Company": "Co",
                    "Location": "",
                    "Posted": "",
                    "Hiring Manager": hm,
                    "AI Score": "8",
                    "Reason": "r",
                    "Source": "instahyre",
                    "Link": "https://example.com/job",
                    "Status": "New",
                    "Notes": "",
                }
            ]
        )

    def _persist_row(self, hm: str, prior_hm: str) -> None:
        from db.services.dashboard_write import persist_dashboard_job_edits

        prior = self._editor_row(hm=prior_hm)
        row = {
            "JOB_KEY": "pm::co",
            "JOB_KEY_V2": "v2:instahyre:co:888",
            "pipeline_stage": "New",
            "applied": False,
            "rejected": False,
            "interview": False,
            "offer": False,
            "notes": "",
            "hiring_manager": hm,
            "company": "Co",
            "source": "instahyre",
        }
        persist_dashboard_job_edits(pd.DataFrame([row]), prior_df=prior)

    def test_persist_hm_change_writes_job_and_recruiter(self) -> None:
        from db.engine import get_session
        from db.models.schema import Job, Recruiter, RecruiterJobLink
        from db.services.dashboard_write import persist_dashboard_job_edits

        self._seed_job()
        prior = self._editor_row(hm="Not Specified")
        row = {
            "JOB_KEY": "pm::co",
            "JOB_KEY_V2": "v2:instahyre:co:888",
            "pipeline_stage": "New",
            "applied": False,
            "rejected": False,
            "interview": False,
            "offer": False,
            "notes": "",
            "hiring_manager": "Alice Recruiter",
            "company": "Co",
            "source": "instahyre",
        }

        count = persist_dashboard_job_edits(pd.DataFrame([row]), prior_df=prior)
        self.assertEqual(count, 1)

        with get_session() as session:
            job = session.execute(
                select(Job).where(Job.job_key_v2 == "v2:instahyre:co:888")
            ).scalar_one()
            self.assertEqual(job.hiring_manager, "Alice Recruiter")
            self.assertEqual(session.query(Recruiter).count(), 1)
            self.assertEqual(session.query(RecruiterJobLink).count(), 1)

    def test_persist_hm_a_to_b_does_not_remove_a_link(self) -> None:
        from db.engine import get_session
        from db.models.schema import RecruiterJobLink

        self._seed_job()
        self._persist_row("Alice Recruiter", "Not Specified")
        self._persist_row("Bob Recruiter", "Alice Recruiter")

        with get_session() as session:
            self.assertEqual(session.query(RecruiterJobLink).count(), 2)

    def test_job_editor_dirty_when_only_hiring_manager_changes(self) -> None:
        from job_editor import job_editor_return_differs_input

        before = self._editor_row(hm="Not Specified")
        after = self._editor_row(hm="Alice Recruiter")
        self.assertTrue(job_editor_return_differs_input(before, after))


if __name__ == "__main__":
    unittest.main()
