"""Tests for acquisition run history reads and dashboard table builders."""

from __future__ import annotations

import os
import sys
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

_REPO_ROOT = Path(__file__).resolve().parent.parent
for entry in (str(_REPO_ROOT), str(_REPO_ROOT / "dashboard"), str(_REPO_ROOT / "src")):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from acquisition_ui import (  # noqa: E402
    acquisition_health_label,
    build_acquisition_run_history_df,
)
from db.read.acquisition_runs import (  # noqa: E402
    INSTAHYRE_INTERESTED_SYNC_NOTES,
    group_acquisition_runs_for_dashboard,
    load_acquisition_run_history,
    load_latest_acquisition_run_dashboard_info,
)


def _clear_db_caches() -> None:
    from db.engine import get_engine, get_session_factory

    get_engine.cache_clear()
    get_session_factory.cache_clear()


def _seed_acquisition_history_db(db_path: Path) -> None:
    os.environ["AI_JOB_AGENT_DB_PATH"] = str(db_path)
    os.environ["SQLITE_ENABLED"] = "1"
    _clear_db_caches()

    from db.bootstrap import ensure_database_ready
    from db.engine import get_session
    from db.models.schema import (
        AcquisitionQueryRun,
        AcquisitionRun,
        Job,
        JobObservation,
    )

    ensure_database_ready()
    now = datetime.now(UTC).replace(tzinfo=None)

    with get_session() as session:
        run_old = AcquisitionRun(
            started_at=now,
            completed_at=now,
            status="completed",
            notes="older",
        )
        run_new = AcquisitionRun(
            started_at=now,
            completed_at=now,
            status="completed",
            notes="newer",
        )
        session.add_all([run_old, run_new])
        session.flush()

        job_new = Job(
            job_key="k::new",
            job_key_v2="v2:new",
            title="PM",
            company="Acme",
            location="Remote",
            source="linkedin",
            link="https://example.com/new",
            updated_at=now,
        )
        job_existing = Job(
            job_key="k::old",
            job_key_v2="v2:old",
            title="Eng",
            company="Beta",
            location="Remote",
            source="instahyre",
            link="https://example.com/old",
            updated_at=now,
        )
        session.add_all([job_new, job_existing])
        session.flush()

        session.add(
            JobObservation(
                job_id=job_existing.id,
                run_id=run_old.id,
                source="instahyre",
                observed_at=now,
                times_seen=1,
            )
        )
        session.add(
            JobObservation(
                job_id=job_existing.id,
                run_id=run_new.id,
                source="instahyre",
                observed_at=now,
                times_seen=2,
            )
        )
        session.add(
            JobObservation(
                job_id=job_new.id,
                run_id=run_new.id,
                source="linkedin",
                observed_at=now,
                times_seen=1,
            )
        )
        session.add(
            AcquisitionQueryRun(
                run_id=run_new.id,
                query_id="q1",
                source="linkedin",
                started_at=now,
                completed_at=now,
                jobs_collected=1,
            )
        )
        session.add(
            AcquisitionQueryRun(
                run_id=run_new.id,
                query_id="feed1",
                source="instahyre",
                started_at=now,
                completed_at=now,
                jobs_collected=1,
            )
        )
        session.commit()


class AcquisitionRunReadTests(unittest.TestCase):
    def setUp(self) -> None:
        import paths

        test_dir = paths.ensure_data_dir() / ".test_dbs"
        test_dir.mkdir(parents=True, exist_ok=True)
        self._db_path = test_dir / f"acq_runs_{os.getpid()}_{id(self)}.db"
        if self._db_path.exists():
            self._db_path.unlink()
        _seed_acquisition_history_db(self._db_path)

    def tearDown(self) -> None:
        _clear_db_caches()
        if self._db_path.exists():
            self._db_path.unlink()
        os.environ.pop("AI_JOB_AGENT_DB_PATH", None)
        os.environ.pop("SQLITE_ENABLED", None)

    def test_latest_run_aggregates_job_counts(self) -> None:
        from db.read.engine import get_read_session

        with get_read_session() as session:
            latest = load_latest_acquisition_run_dashboard_info(session)
        self.assertIsNotNone(latest)
        self.assertEqual(int(latest["jobs_discovered"]), 2)
        self.assertEqual(int(latest["new_jobs"]), 1)
        self.assertEqual(int(latest["existing_jobs"]), 1)
        self.assertEqual(int(latest["sources_run"]), 2)

    def test_history_orders_most_recent_first(self) -> None:
        from db.read.engine import get_read_session

        with get_read_session() as session:
            rows = load_acquisition_run_history(session, limit=10)
        self.assertEqual(len(rows), 2)
        self.assertGreater(int(rows[0]["run_id"]), int(rows[1]["run_id"]))


class AcquisitionInterestedSyncGroupingTests(unittest.TestCase):
    def setUp(self) -> None:
        import paths

        test_dir = paths.ensure_data_dir() / ".test_dbs"
        test_dir.mkdir(parents=True, exist_ok=True)
        self._db_path = test_dir / f"acq_group_{os.getpid()}_{id(self)}.db"
        if self._db_path.exists():
            self._db_path.unlink()
        os.environ["AI_JOB_AGENT_DB_PATH"] = str(self._db_path)
        os.environ["SQLITE_ENABLED"] = "1"
        _clear_db_caches()
        from db.bootstrap import ensure_database_ready

        ensure_database_ready()

    def tearDown(self) -> None:
        _clear_db_caches()
        if self._db_path.exists():
            self._db_path.unlink()
        os.environ.pop("AI_JOB_AGENT_DB_PATH", None)
        os.environ.pop("SQLITE_ENABLED", None)

    def test_interested_sync_folded_into_parent_run(self) -> None:
        from datetime import timedelta

        from db.read.engine import get_read_session

        now = datetime.now(UTC).replace(tzinfo=None)
        with get_read_session() as session:
            from db.models.schema import AcquisitionRun, Job, JobObservation

            sync_run = AcquisitionRun(
                started_at=now - timedelta(hours=1),
                completed_at=now - timedelta(minutes=50),
                status="completed",
                notes=INSTAHYRE_INTERESTED_SYNC_NOTES,
            )
            main_run = AcquisitionRun(
                started_at=now - timedelta(minutes=30),
                completed_at=now,
                status="completed",
                notes="phase_c_runtime_dual_write",
            )
            session.add_all([sync_run, main_run])
            session.flush()
            job = Job(
                job_key="k::sync",
                job_key_v2="v2:sync",
                title="PM",
                company="Acme",
                source="instahyre",
                link="https://example.com/sync",
                updated_at=now,
            )
            session.add(job)
            session.flush()
            session.add(
                JobObservation(
                    job_id=job.id,
                    run_id=sync_run.id,
                    source="instahyre",
                    observed_at=now,
                    times_seen=1,
                )
            )
            session.commit()
            main_id = int(main_run.id)
            sync_id = int(sync_run.id)

        with get_read_session() as session:
            rows = load_acquisition_run_history(session, limit=10)

        self.assertEqual(len(rows), 1)
        self.assertEqual(int(rows[0]["run_id"]), main_id)
        sync = rows[0].get("interested_sync")
        self.assertIsInstance(sync, dict)
        assert isinstance(sync, dict)
        self.assertEqual(int(sync["run_id"]), sync_id)
        self.assertEqual(int(sync["jobs_discovered"]), 1)


class AcquisitionRunHistoryTableTests(unittest.TestCase):
    def test_build_history_df_labels_runs(self) -> None:
        df = build_acquisition_run_history_df(
            [
                {
                    "run_id": 41,
                    "started_at": datetime(2026, 6, 23, 9, 0, 0),
                    "completed_at": datetime(2026, 6, 23, 10, 30, 0),
                    "status": "completed",
                    "sources_list": "linkedin,instahyre",
                    "jobs_discovered": 120,
                    "new_jobs": 15,
                    "existing_jobs": 105,
                }
            ]
        )
        self.assertEqual(df.iloc[0]["Run"], "Run 41")
        self.assertNotIn("Type", df.columns)
        sources_idx = list(df.columns).index("Sources")
        substep_idx = list(df.columns).index("Sub-step")
        self.assertEqual(substep_idx, sources_idx + 1)
        self.assertEqual(df.iloc[0]["Jobs Discovered"], 120)
        self.assertEqual(df.iloc[0]["New Jobs"], 15)
        self.assertEqual(df.iloc[0]["Existing Jobs"], 105)
        self.assertEqual(df.iloc[0]["Sources"], "linkedin,instahyre")
        self.assertIn("Trigger", df.columns)
        self.assertEqual(df.iloc[0]["Trigger"], "—")
        self.assertEqual(df.iloc[0]["Failed Sources"], "—")

    def test_build_history_df_shows_run_trigger(self) -> None:
        df = build_acquisition_run_history_df(
            [
                {
                    "run_id": 42,
                    "started_at": datetime(2026, 6, 23, 9, 0, 0),
                    "completed_at": datetime(2026, 6, 23, 9, 30, 0),
                    "status": "completed",
                    "run_trigger": "manual",
                    "sources_list": "linkedin",
                    "jobs_discovered": 1,
                    "new_jobs": 1,
                    "existing_jobs": 0,
                }
            ]
        )
        self.assertEqual(df.iloc[0]["Trigger"], "Manual")

    def test_acquisition_health_label_maps_status(self) -> None:
        self.assertEqual(acquisition_health_label("completed"), "Healthy")
        self.assertEqual(acquisition_health_label("failed"), "Degraded")


class AcquisitionRunHistoryReadMockTests(unittest.TestCase):
    def test_load_history_passes_limit(self) -> None:
        session = MagicMock()
        session.execute.return_value.mappings.return_value.all.return_value = []
        load_acquisition_run_history(session, limit=50)
        self.assertEqual(session.execute.call_args[0][1], {"limit": 50})
        sql = str(session.execute.call_args[0][0])
        self.assertIn("ar.run_trigger", sql)


if __name__ == "__main__":
    unittest.main()
