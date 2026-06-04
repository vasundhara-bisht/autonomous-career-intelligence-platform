"""Tests for Phase D1 dashboard SQLite read loaders."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
for entry in (str(_REPO_ROOT), str(_SRC)):
    if entry not in sys.path:
        sys.path.insert(0, entry)


def _clear_db_caches() -> None:
    from db.engine import get_engine, get_session_factory

    get_engine.cache_clear()
    get_session_factory.cache_clear()


def _seed_minimal_db(db_path: Path) -> None:
    from datetime import UTC, datetime

    os.environ["AI_JOB_AGENT_DB_PATH"] = str(db_path)
    os.environ["SQLITE_ENABLED"] = "1"
    _clear_db_caches()

    from db.bootstrap import ensure_database_ready
    from db.engine import get_session
    from db.models.schema import (
        AcquisitionRun,
        AiEvaluation,
        Job,
        JobObservation,
        UserJobState,
    )

    ensure_database_ready()
    now = datetime.now(UTC).replace(tzinfo=None)
    with get_session() as session:
        run = AcquisitionRun(
            started_at=now,
            completed_at=now,
            status="completed",
            notes="test_run",
        )
        session.add(run)
        session.flush()
        run_id = run.id
        job = Job(
            job_key="pm::acme",
            job_key_v2="v2:test:1",
            title="PM",
            company="Acme",
            location="Bangalore",
            source="instahyre",
            link="https://example.com/job-1",
            time_posted="2d",
            updated_at=now,
        )
        session.add(job)
        session.flush()
        session.add(
            AiEvaluation(
                job_id=job.id,
                run_id=run_id,
                ai_status="pending",
                ai_score=None,
                reason="",
                model="test",
                evaluated_at=now,
            )
        )
        session.add(
            JobObservation(
                job_id=job.id,
                run_id=run_id,
                observed_at=now,
                currently_active=True,
                times_seen=1,
            )
        )
        session.add(
            UserJobState(
                job_id=job.id,
                applied=False,
                rejected=False,
                interview=False,
                offer=False,
                pipeline_stage="New",
                updated_at=now,
            )
        )
        session.commit()


class DashboardReadFlagTests(unittest.TestCase):
    def tearDown(self) -> None:
        for key in ("SQLITE_ENABLED", "SQLITE_READ", "SQLITE_DASHBOARD_WRITE"):
            os.environ.pop(key, None)

    def test_dashboard_gates_default_on_without_env(self) -> None:
        from db.read.engine import dashboard_read_enabled, dashboard_write_enabled

        keys = ("SQLITE_ENABLED", "SQLITE_READ", "SQLITE_DASHBOARD_WRITE")
        saved = {k: os.environ.pop(k, None) for k in keys}
        try:
            self.assertTrue(dashboard_read_enabled())
            self.assertTrue(dashboard_write_enabled())
        finally:
            for k, v in saved.items():
                if v is not None:
                    os.environ[k] = v

    def test_dashboard_read_requires_both_flags(self) -> None:
        from db.read.engine import dashboard_read_enabled

        os.environ["SQLITE_ENABLED"] = "0"
        os.environ["SQLITE_READ"] = "1"
        self.assertFalse(dashboard_read_enabled())

        os.environ["SQLITE_ENABLED"] = "1"
        os.environ["SQLITE_READ"] = "0"
        self.assertFalse(dashboard_read_enabled())

        os.environ["SQLITE_ENABLED"] = "1"
        os.environ["SQLITE_READ"] = "1"
        self.assertTrue(dashboard_read_enabled())


class DashboardTransformTests(unittest.TestCase):
    def test_pending_ai_not_scored(self) -> None:
        from db.read.transforms import apply_dashboard_job_ai_columns

        df = pd.DataFrame(
            [{"ai_status": "pending", "ai_score": pd.NA, "reason": ""}]
        )
        out = apply_dashboard_job_ai_columns(df)
        self.assertFalse(bool(out.iloc[0]["is_ai_scored"]))
        self.assertEqual(float(out.iloc[0]["score"]), 0.0)

    def test_scored_job_has_score(self) -> None:
        from db.read.transforms import apply_dashboard_job_ai_columns

        df = pd.DataFrame(
            [{"ai_status": "scored", "ai_score": 8.5, "reason": "fit"}]
        )
        out = apply_dashboard_job_ai_columns(df)
        self.assertTrue(bool(out.iloc[0]["is_ai_scored"]))
        self.assertEqual(float(out.iloc[0]["score"]), 8.5)


class JobsCsvAlignedViewTests(unittest.TestCase):
    def setUp(self) -> None:
        import paths

        test_dir = paths.ensure_data_dir() / ".test_dbs"
        test_dir.mkdir(parents=True, exist_ok=True)
        self._db_path = test_dir / f"d1_loaders_{os.getpid()}_{id(self)}.db"
        if self._db_path.exists():
            self._db_path.unlink()
        _seed_minimal_db(self._db_path)

        self._tmpdir = tempfile.TemporaryDirectory()
        self._jobs_csv = Path(self._tmpdir.name) / "jobs.csv"
        self._jobs_csv.write_text(
            "JOB_KEY,JOB_KEY_V2,title,company,location,link,source,time_posted,"
            "hiring_manager,ai_score,ai_status,reason\n"
            "pm::acme,v2:test:1,PM,Acme,Bangalore,https://example.com/job-1,"
            "instahyre,2d,Not Specified,,pending,\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self._tmpdir.cleanup()
        _clear_db_caches()
        if self._db_path.exists():
            self._db_path.unlink()
        os.environ.pop("AI_JOB_AGENT_DB_PATH", None)
        os.environ.pop("SQLITE_ENABLED", None)

    def test_aligned_view_matches_jobs_csv_key_count(self) -> None:
        from db.read.engine import get_read_session
        from db.read.export_cohort import load_jobs_csv_aligned_view_df

        with get_read_session() as session:
            df, fallback_count = load_jobs_csv_aligned_view_df(session, self._jobs_csv)
        self.assertEqual(len(df), 1)
        self.assertEqual(df.iloc[0]["JOB_KEY_V2"], "v2:test:1")
        self.assertEqual(fallback_count, 0)

    def test_missing_view_key_uses_csv_fallback(self) -> None:
        from db.read.engine import get_read_session
        from db.read.export_cohort import load_jobs_csv_aligned_view_df

        self._jobs_csv.write_text(
            "JOB_KEY,JOB_KEY_V2,title,company,location,link,source,time_posted,"
            "hiring_manager,ai_score,ai_status,reason\n"
            "pm::acme,v2:test:1,PM,Acme,Bangalore,https://example.com/job-1,"
            "instahyre,2d,Not Specified,,pending,\n"
            "pm::other,v2:test:missing,PM,Other,Mumbai,https://example.com/job-2,"
            "instahyre,1d,Not Specified,,pending,\n",
            encoding="utf-8",
        )
        with get_read_session() as session:
            df, fallback_count = load_jobs_csv_aligned_view_df(session, self._jobs_csv)
        self.assertEqual(len(df), 2)
        self.assertGreaterEqual(fallback_count, 1)


class DashboardLoaderRoutingTests(unittest.TestCase):
    def tearDown(self) -> None:
        for key in ("SQLITE_ENABLED", "SQLITE_READ", "SQLITE_DASHBOARD_WRITE"):
            os.environ.pop(key, None)

    def test_sqlite_read_off_uses_csv_path(self) -> None:
        from dashboard.loaders import load_dashboard_jobs_df

        os.environ["SQLITE_READ"] = "0"
        frame = pd.DataFrame(
            [
                {
                    "JOB_KEY": "k1",
                    "JOB_KEY_V2": "v2:csv:1",
                    "title": "T",
                    "company": "C",
                    "location": "L",
                    "link": "https://x",
                    "source": "test",
                    "time_posted": "1d",
                    "hiring_manager": "Not Specified",
                    "ai_status": "pending",
                }
            ]
        )
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            frame.to_csv(f.name, index=False)
            jobs_path = Path(f.name)

        try:
            with patch("dashboard.loaders.paths.jobs_csv", return_value=jobs_path):
                with patch(
                    "dashboard.loaders.dashboard_read_enabled", return_value=False
                ):
                    with patch(
                        "dashboard.loaders._load_jobs_from_sqlite"
                    ) as sqlite_load:
                        out = load_dashboard_jobs_df()
                        sqlite_load.assert_not_called()
            self.assertEqual(len(out), 1)
            self.assertFalse(bool(out.iloc[0]["is_ai_scored"]))
        finally:
            jobs_path.unlink(missing_ok=True)

    def test_sqlite_failure_falls_back_to_csv(self) -> None:
        from dashboard.loaders import load_dashboard_jobs_df

        frame = pd.DataFrame(
            [
                {
                    "JOB_KEY": "k1",
                    "JOB_KEY_V2": "v2:csv:1",
                    "title": "T",
                    "company": "C",
                    "location": "L",
                    "link": "https://x",
                    "source": "test",
                    "time_posted": "1d",
                    "hiring_manager": "Not Specified",
                    "ai_status": "scored",
                    "ai_score": 7,
                }
            ]
        )
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            frame.to_csv(f.name, index=False)
            jobs_path = Path(f.name)

        try:
            with patch("dashboard.loaders.paths.jobs_csv", return_value=jobs_path):
                with patch(
                    "dashboard.loaders.dashboard_read_enabled", return_value=True
                ):
                    with patch(
                        "dashboard.loaders._load_jobs_from_sqlite",
                        side_effect=RuntimeError("db down"),
                    ):
                        out = load_dashboard_jobs_df()
            self.assertEqual(len(out), 1)
            self.assertTrue(bool(out.iloc[0]["is_ai_scored"]))
        finally:
            jobs_path.unlink(missing_ok=True)


class DashboardCrmLoaderTests(unittest.TestCase):
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
            },
            clear=False,
        )
        self._env_patch.start()
        _clear_db_caches()

    def tearDown(self) -> None:
        self._env_patch.stop()
        _clear_db_caches()
        self._tmpdir.cleanup()

    def test_crm_loader_reads_active_recruiters_view(self) -> None:
        from datetime import UTC, datetime

        from db.bootstrap import ensure_database_ready
        from db.engine import get_session
        from db.models.schema import Recruiter
        from dashboard.loaders import load_recruiter_crm_df

        ensure_database_ready()
        now = datetime.now(UTC).replace(tzinfo=None)
        with get_session() as session:
            session.add(
                Recruiter(
                    recruiter_key="jane doe",
                    recruiter_name="Jane Doe",
                    current_company="Acme",
                    source="instahyre",
                    first_seen=now,
                    last_seen=now,
                    jobs_connected=2,
                    recruiter_stage="discovered",
                    currently_active=True,
                )
            )
            session.commit()

        df = load_recruiter_crm_df()
        self.assertGreaterEqual(len(df), 1)
        self.assertIn("jane doe", set(df["RECRUITER_KEY"].astype(str)))


class DashboardWriteRoundTripTests(unittest.TestCase):
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

    def test_job_state_write_round_trip(self) -> None:
        from datetime import UTC, datetime

        from db.bootstrap import ensure_database_ready
        from db.engine import get_session
        from db.models.schema import Job, UserJobState
        from db.read.historical import load_historical_jobs_view_df
        from db.services.dashboard_write import persist_dashboard_job_edits

        ensure_database_ready()
        v2 = "v2:instahyre:co:777"
        now = datetime.now(UTC).replace(tzinfo=None)
        with get_session() as session:
            job = Job(
                job_key="pm::co",
                job_key_v2=v2,
                title="PM",
                company="Co",
                source="instahyre",
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

        updated = pd.DataFrame(
            [
                {
                    "JOB_KEY": "pm::co",
                    "JOB_KEY_V2": v2,
                    "pipeline_stage": "Applied",
                    "applied": True,
                    "rejected": False,
                    "interview": False,
                    "offer": False,
                    "notes": "dashboard test",
                }
            ]
        )
        count = persist_dashboard_job_edits(updated)
        self.assertEqual(count, 1)

        with get_session() as session:
            hist = load_historical_jobs_view_df(session)
        row = hist[hist["JOB_KEY_V2"] == v2].iloc[0]
        self.assertEqual(str(row["pipeline_stage"]), "Applied")
        self.assertTrue(bool(row["applied"]))
        self.assertEqual(str(row["notes"]), "dashboard test")

    def test_recruiter_stage_write_round_trip(self) -> None:
        from datetime import UTC, datetime

        from db.bootstrap import ensure_database_ready
        from db.engine import get_session
        from db.models.schema import Recruiter
        from db.read.crm import load_active_recruiters_view_df
        from db.services.dashboard_write import persist_dashboard_crm_edits

        ensure_database_ready()
        now = datetime.now(UTC).replace(tzinfo=None)
        with get_session() as session:
            session.add(
                Recruiter(
                    recruiter_key="bob smith",
                    recruiter_name="Bob Smith",
                    recruiter_stage="discovered",
                    first_seen=now,
                    last_seen=now,
                    currently_active=True,
                )
            )
            session.commit()

        count = persist_dashboard_crm_edits(["bob smith"], ["warm"])
        self.assertEqual(count, 1)

        with get_session() as session:
            df = load_active_recruiters_view_df(session)
        row = df[df["RECRUITER_KEY"] == "bob smith"].iloc[0]
        self.assertEqual(str(row["recruiter_stage"]), "warm")


if __name__ == "__main__":
    unittest.main()
