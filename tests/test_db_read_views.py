"""Tests for Phase D0 SQLite read views and read-model loaders."""

from __future__ import annotations

import os
import sys
import unittest
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import text

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
    os.environ["AI_JOB_AGENT_DB_PATH"] = str(db_path)
    os.environ["SQLITE_ENABLED"] = "1"
    _clear_db_caches()

    from db.bootstrap import ensure_database_ready
    from db.engine import get_session
    from db.models.schema import (
        AcquisitionQueryRun,
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
                ai_status="scored",
                ai_score=9.0,
                reason="fit",
                model="test",
                evaluated_at=now,
            )
        )
        query_run = AcquisitionQueryRun(
            run_id=run_id,
            query_id="feed1",
            query_label="pm feed",
            query_role="feed",
            run_ts="2026-01-01T00:00:00+00:00",
            source="instahyre",
            started_at=now,
            completed_at=now,
            jobs_collected=1,
        )
        session.add(query_run)
        session.flush()

        session.add(
            JobObservation(
                job_id=job.id,
                run_id=run_id,
                query_run_id=query_run.id,
                observed_at=now,
                currently_active=True,
                times_seen=2,
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


class DbReadViewsTests(unittest.TestCase):
    def setUp(self) -> None:
        import paths

        test_dir = paths.ensure_data_dir() / ".test_dbs"
        test_dir.mkdir(parents=True, exist_ok=True)
        self._db_path = test_dir / f"read_views_{os.getpid()}_{id(self)}.db"
        if self._db_path.exists():
            self._db_path.unlink()
        os.environ["SQLITE_ENABLED"] = "1"
        _seed_minimal_db(self._db_path)

    def tearDown(self) -> None:
        _clear_db_caches()
        if self._db_path.exists():
            self._db_path.unlink()
        os.environ.pop("AI_JOB_AGENT_DB_PATH", None)
        os.environ.pop("SQLITE_ENABLED", None)

    def test_read_views_exist(self) -> None:
        from db.read.engine import get_read_session
        from db.read.views import assert_read_views_present, missing_read_views

        with get_read_session() as session:
            assert_read_views_present(session)
            self.assertEqual(missing_read_views(session), [])

    def test_latest_ai_evaluations_unique_job_id(self) -> None:
        from db.read.engine import get_read_session

        with get_read_session() as session:
            rows = session.execute(
                text(
                    """
                    SELECT job_id, COUNT(*) AS n
                    FROM latest_ai_evaluations_view
                    GROUP BY job_id
                    HAVING COUNT(*) > 1
                    """
                )
            ).all()
            self.assertEqual(rows, [])

    def test_current_export_cohort_matches_latest_run(self) -> None:
        from db.read.engine import get_read_session
        from db.read.export_cohort import load_export_cohort_keys, load_latest_run_info

        with get_read_session() as session:
            run_info = load_latest_run_info(session)
            self.assertIsNotNone(run_info)
            keys = load_export_cohort_keys(session)
            self.assertIn("v2:test:1", keys)

    def test_historical_jobs_view_row_count(self) -> None:
        from db.read.engine import get_read_session
        from db.read.historical import load_historical_jobs_view_df

        with get_read_session() as session:
            df = load_historical_jobs_view_df(session)
            self.assertEqual(len(df), 1)
            self.assertEqual(df.iloc[0]["JOB_KEY_V2"], "v2:test:1")

    def test_current_jobs_view_transforms(self) -> None:
        from db.read.engine import get_read_session
        from db.read.export_cohort import load_current_jobs_view_df

        with get_read_session() as session:
            df = load_current_jobs_view_df(session, apply_transforms=True)
            self.assertEqual(len(df), 1)
            self.assertTrue(bool(df.iloc[0]["priority"]))
            self.assertEqual(str(df.iloc[0]["ai_status"]), "scored")

    def test_current_jobs_export_source_raw(self) -> None:
        from db.read.engine import get_read_session
        from db.read.export_cohort import load_current_jobs_export_source_df

        with get_read_session() as session:
            df = load_current_jobs_export_source_df(session)
            self.assertEqual(len(df), 1)
            self.assertIn("ai_score", df.columns)
            self.assertNotIn("priority", df.columns)

    def test_current_jobs_view_metadata_from_query_run(self) -> None:
        from db.read.engine import get_read_session
        from db.read.export_cohort import load_current_jobs_export_source_df

        with get_read_session() as session:
            df = load_current_jobs_export_source_df(session)
            self.assertEqual(len(df), 1)
            row = df.iloc[0]
            self.assertEqual(str(row["instahyre_feed_id"]), "feed1")
            self.assertEqual(str(row["instahyre_query_id"]), "feed1")
            self.assertEqual(str(row["instahyre_query_label"]), "pm feed")
            self.assertEqual(str(row["instahyre_run_ts"]), "2026-01-01T00:00:00+00:00")

    def test_shadow_compare_empty_csv(self) -> None:
        import pandas as pd

        from db.read.shadow import compare_jobs_csv_to_view

        report = compare_jobs_csv_to_view(pd.DataFrame(), pd.DataFrame())
        self.assertTrue(report.ok())


class ReadModelTransformTests(unittest.TestCase):
    def test_is_bangalore_priority(self) -> None:
        from db.read.transforms import is_bangalore_priority

        self.assertTrue(is_bangalore_priority("Bangalore, Karnataka"))
        self.assertFalse(is_bangalore_priority("Mumbai"))


if __name__ == "__main__":
    unittest.main()
