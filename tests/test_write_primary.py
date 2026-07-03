"""Tests for D5 SQLite write-primary switch."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import UTC, datetime
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


class WritePrimaryFlagTests(unittest.TestCase):
    def test_write_primary_default_on_without_env(self) -> None:
        from db.write.engine import (
            export_crm_csv_enabled,
            export_descriptions_csv_enabled,
            export_historical_csv_enabled,
            write_primary_enabled,
        )

        keys = (
            "SQLITE_ENABLED",
            "SQLITE_DUAL_WRITE",
            "SQLITE_WRITE_PRIMARY",
            "SQLITE_EXPORT_HISTORICAL_CSV",
            "SQLITE_EXPORT_DESCRIPTIONS_CSV",
            "SQLITE_EXPORT_CRM_CSV",
        )
        saved = {k: os.environ.pop(k, None) for k in keys}
        try:
            self.assertTrue(write_primary_enabled())
            self.assertFalse(export_historical_csv_enabled())
            self.assertFalse(export_descriptions_csv_enabled())
            self.assertFalse(export_crm_csv_enabled())
        finally:
            for k, v in saved.items():
                if v is not None:
                    os.environ[k] = v

    def test_write_primary_requires_dual_write(self) -> None:
        from db.write.engine import write_primary_enabled

        with patch.dict(
            os.environ,
            {
                "SQLITE_ENABLED": "1",
                "SQLITE_DUAL_WRITE": "0",
                "SQLITE_WRITE_PRIMARY": "1",
            },
            clear=False,
        ):
            self.assertFalse(write_primary_enabled())

    def test_write_primary_enabled(self) -> None:
        from db.write.engine import write_primary_enabled

        with patch.dict(
            os.environ,
            {
                "SQLITE_ENABLED": "1",
                "SQLITE_DUAL_WRITE": "1",
                "SQLITE_WRITE_PRIMARY": "1",
            },
            clear=False,
        ):
            self.assertTrue(write_primary_enabled())

    def test_export_jobs_csv_off(self) -> None:
        from db.write.engine import export_jobs_csv_enabled

        with patch.dict(
            os.environ,
            {
                "SQLITE_ENABLED": "1",
                "SQLITE_WRITE_PRIMARY": "1",
                "SQLITE_EXPORT_JOBS_CSV": "0",
            },
            clear=False,
        ):
            self.assertFalse(export_jobs_csv_enabled())


class HistoricalCsvGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._data = Path(self._tmpdir.name)
        self._env_patch = patch.dict(
            os.environ,
            {
                "AI_JOB_AGENT_DATA_DIR": str(self._data),
                "SQLITE_ENABLED": "1",
                "SQLITE_DUAL_WRITE": "1",
                "SQLITE_WRITE_PRIMARY": "1",
            },
            clear=False,
        )
        self._env_patch.start()
        import paths

        self._data_dir_patch = patch.object(paths, "DATA_DIR", self._data)
        self._data_dir_patch.start()

    def tearDown(self) -> None:
        self._data_dir_patch.stop()
        self._env_patch.stop()
        self._tmpdir.cleanup()

    def test_update_historical_jobs_skips_csv(self) -> None:
        import paths
        from agent.historical_persistence import update_historical_jobs

        hist_path = paths.historical_jobs_csv()
        hist_path.parent.mkdir(parents=True, exist_ok=True)
        hist_path.write_text("JOB_KEY,JOB_KEY_V2\n", encoding="utf-8")
        mtime_before = hist_path.stat().st_mtime

        update_historical_jobs([{"JOB_KEY_V2": "v2:test:1", "JOB_KEY": "k::c"}])

        self.assertEqual(hist_path.stat().st_mtime, mtime_before)


class DescriptionFlushGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._data = Path(self._tmpdir.name)
        self._env_patch = patch.dict(
            os.environ,
            {
                "AI_JOB_AGENT_DATA_DIR": str(self._data),
                "SQLITE_ENABLED": "1",
                "SQLITE_DUAL_WRITE": "1",
                "SQLITE_WRITE_PRIMARY": "1",
            },
            clear=False,
        )
        self._env_patch.start()
        import paths

        self._data_dir_patch = patch.object(paths, "DATA_DIR", self._data)
        self._data_dir_patch.start()

    def tearDown(self) -> None:
        self._data_dir_patch.stop()
        self._env_patch.stop()
        self._tmpdir.cleanup()

    def test_flush_description_store_skips_csv(self) -> None:
        import paths
        from agent.job_description_persistence import DescriptionStore, flush_description_store

        desc_path = paths.job_descriptions_csv()
        desc_path.parent.mkdir(parents=True, exist_ok=True)
        store = DescriptionStore()
        store.put(
            legacy_key="pm::acme",
            v2_key="v2:gh:acme:1",
            record={
                "description": "A" * 250,
                "last_updated": "2026-01-01 00:00:00",
                "source": "greenhouse",
            },
        )
        flush_description_store(store)
        self.assertFalse(desc_path.is_file())


class DbCsvExportTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._data = Path(self._tmpdir.name)
        self._env_patch = patch.dict(
            os.environ,
            {
                "AI_JOB_AGENT_DATA_DIR": str(self._data),
                "AI_JOB_AGENT_DB_PATH": str(self._data / "test.db"),
                "SQLITE_ENABLED": "1",
            },
            clear=False,
        )
        self._env_patch.start()
        _clear_db_caches()

    def tearDown(self) -> None:
        self._env_patch.stop()
        _clear_db_caches()
        self._tmpdir.cleanup()

    def test_export_historical_matches_view(self) -> None:
        from db.bootstrap import ensure_database_ready
        from db.engine import get_session
        from db.models.schema import (
            AcquisitionRun,
            AiEvaluation,
            Job,
            JobDescription,
            JobObservation,
            UserJobState,
        )
        from db.write.csv_export import export_historical_jobs_csv, export_job_descriptions_csv
        import paths

        ensure_database_ready()
        v2 = "v2:greenhouse:acme:exp1"
        now = datetime.now(UTC).replace(tzinfo=None)
        with get_session() as session:
            run = AcquisitionRun(
                started_at=now,
                completed_at=now,
                status="completed",
            )
            session.add(run)
            session.flush()
            job = Job(
                job_key="pm::acme",
                job_key_v2=v2,
                title="PM",
                company="Acme",
                source="greenhouse",
            )
            session.add(job)
            session.flush()
            session.add(
                AiEvaluation(
                    job_id=job.id,
                    ai_status="scored",
                    ai_score=8.0,
                    reason="fit",
                    evaluated_at=now,
                )
            )
            session.add(
                JobObservation(
                    job_id=job.id,
                    run_id=run.id,
                    source="greenhouse",
                    observed_at=now,
                    times_seen=1,
                )
            )
            session.add(UserJobState(job_id=job.id, applied=False, rejected=False))
            session.add(
                JobDescription(
                    job_id=job.id,
                    job_key_v2=v2,
                    description="B" * 250,
                    source="greenhouse",
                    last_updated=now,
                )
            )
            session.commit()

        with get_session() as session:
            count = export_historical_jobs_csv(session)
        self.assertGreaterEqual(count, 1)
        hist = pd.read_csv(paths.historical_jobs_csv())
        self.assertIn(v2, set(hist["JOB_KEY_V2"].astype(str)))

        with get_session() as session:
            desc_count = export_job_descriptions_csv(session)
        self.assertGreaterEqual(desc_count, 1)
        desc = pd.read_csv(paths.job_descriptions_csv())
        self.assertIn(v2, set(desc["JOB_KEY_V2"].astype(str)))


if __name__ == "__main__":
    unittest.main()
