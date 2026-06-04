"""Tests for D7 SQLite reset truncate and export/SOT tooling."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
for entry in (str(_REPO_ROOT), str(_SRC)):
    if entry not in sys.path:
        sys.path.insert(0, entry)


def _clear_db_caches() -> None:
    from db.engine import get_engine, get_session_factory

    get_engine.cache_clear()
    get_session_factory.cache_clear()


class ResetSqliteTruncateTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._data = Path(self._tmpdir.name)
        os.environ["AI_JOB_AGENT_DATA_DIR"] = str(self._data)
        os.environ["AI_JOB_AGENT_DB_PATH"] = str(self._data / "test.db")
        os.environ["SQLITE_ENABLED"] = "1"
        _clear_db_caches()

    def tearDown(self) -> None:
        _clear_db_caches()
        self._tmpdir.cleanup()
        for key in ("AI_JOB_AGENT_DATA_DIR", "AI_JOB_AGENT_DB_PATH", "SQLITE_ENABLED"):
            os.environ.pop(key, None)

    def test_bootstrap_truncates_all_product_tables(self) -> None:
        from db.bootstrap import ensure_database_ready
        from db.engine import get_session
        from db.models.schema import Job, Recruiter
        from db.reset_sqlite import product_table_counts, truncate_profile_tables

        ensure_database_ready()
        now = datetime.now(UTC).replace(tzinfo=None)
        with get_session() as session:
            session.add(
                Job(
                    job_key="k",
                    job_key_v2="v2:test:reset",
                    title="T",
                    company="C",
                )
            )
            session.add(
                Recruiter(
                    recruiter_key="r1",
                    recruiter_name="R",
                    first_seen=now,
                    last_seen=now,
                )
            )
            session.commit()

        self.assertGreater(product_table_counts()["jobs"], 0)
        truncated = truncate_profile_tables("bootstrap")
        self.assertIn("jobs", truncated)
        counts = product_table_counts()
        self.assertEqual(counts["jobs"], 0)
        self.assertEqual(counts["recruiters"], 0)

    def test_acquisition_preserves_jobs(self) -> None:
        from db.bootstrap import ensure_database_ready
        from db.engine import get_session
        from db.models.schema import AcquisitionRun, Job, JobObservation
        from db.reset_sqlite import product_table_counts, truncate_profile_tables

        ensure_database_ready()
        now = datetime.now(UTC).replace(tzinfo=None)
        with get_session() as session:
            run = AcquisitionRun(started_at=now, status="completed")
            session.add(run)
            session.flush()
            job = Job(job_key="k", job_key_v2="v2:keep", title="T", company="C")
            session.add(job)
            session.flush()
            session.add(
                JobObservation(
                    job_id=job.id,
                    run_id=run.id,
                    observed_at=now,
                    currently_active=True,
                    times_seen=1,
                )
            )
            session.commit()

        truncate_profile_tables("acquisition")
        counts = product_table_counts()
        self.assertEqual(counts["jobs"], 1)
        self.assertEqual(counts["acquisition_runs"], 0)


class SourceOfTruthParityTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._data = Path(self._tmpdir.name)
        os.environ["AI_JOB_AGENT_DATA_DIR"] = str(self._data)
        os.environ["AI_JOB_AGENT_DB_PATH"] = str(self._data / "test.db")
        os.environ["SQLITE_ENABLED"] = "1"
        _clear_db_caches()

    def tearDown(self) -> None:
        _clear_db_caches()
        self._tmpdir.cleanup()
        for key in ("AI_JOB_AGENT_DATA_DIR", "AI_JOB_AGENT_DB_PATH", "SQLITE_ENABLED"):
            os.environ.pop(key, None)

    def test_sot_detects_csv_extra_key(self) -> None:
        from db.bootstrap import ensure_database_ready
        from db.engine import get_session
        from db.models.schema import AiEvaluation, Job
        from db.services.parity_checks import check_source_of_truth_export_parity
        import pandas as pd

        ensure_database_ready()
        v2 = "v2:test:sot"
        now = datetime.now(UTC).replace(tzinfo=None)
        with get_session() as session:
            job = Job(job_key="k", job_key_v2=v2, title="T", company="C")
            session.add(job)
            session.flush()
            session.add(
                AiEvaluation(
                    job_id=job.id,
                    ai_status="scored",
                    ai_score=7.0,
                    evaluated_at=now,
                )
            )
            session.commit()

        historical = pd.DataFrame(
            [
                {
                    "JOB_KEY": "k",
                    "JOB_KEY_V2": v2,
                    "ai_status": "scored",
                    "ai_score": 7.0,
                },
                {
                    "JOB_KEY": "orphan",
                    "JOB_KEY_V2": "v2:csv:only",
                    "ai_status": "pending",
                },
            ]
        )
        with get_session() as session:
            report = check_source_of_truth_export_parity(
                session,
                historical,
                pd.DataFrame(),
                pd.DataFrame(),
                pd.DataFrame(),
            )
        self.assertFalse(report.ok())
        self.assertTrue(any("not in DB" in f for f in report.failures))


if __name__ == "__main__":
    unittest.main()
