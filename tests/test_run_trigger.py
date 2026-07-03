"""Tests for run trigger env parsing and persistence."""

from __future__ import annotations

import os
import sys
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

_REPO_ROOT = Path(__file__).resolve().parent.parent
for entry in (str(_REPO_ROOT), str(_REPO_ROOT / "dashboard"), str(_REPO_ROOT / "src")):
    if entry not in sys.path:
        sys.path.insert(0, entry)


def _clear_db_caches() -> None:
    from db.engine import get_engine, get_session_factory

    get_engine.cache_clear()
    get_session_factory.cache_clear()


class ReadRunTriggerTests(unittest.TestCase):
    def test_read_run_trigger_accepts_manual_and_scheduled(self) -> None:
        from agent.run_trigger import (
            ACQUISITION_RUN_TRIGGER_ENV,
            read_run_trigger,
        )

        with patch.dict(os.environ, {ACQUISITION_RUN_TRIGGER_ENV: "manual"}, clear=False):
            self.assertEqual(read_run_trigger(ACQUISITION_RUN_TRIGGER_ENV), "manual")
        with patch.dict(os.environ, {ACQUISITION_RUN_TRIGGER_ENV: "SCHEDULED"}, clear=False):
            self.assertEqual(read_run_trigger(ACQUISITION_RUN_TRIGGER_ENV), "scheduled")

    def test_read_run_trigger_rejects_unknown_or_empty(self) -> None:
        from agent.run_trigger import LIFECYCLE_MONITOR_RUN_TRIGGER_ENV, read_run_trigger

        with patch.dict(os.environ, {LIFECYCLE_MONITOR_RUN_TRIGGER_ENV: "kickstart"}, clear=False):
            self.assertIsNone(read_run_trigger(LIFECYCLE_MONITOR_RUN_TRIGGER_ENV))
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop(LIFECYCLE_MONITOR_RUN_TRIGGER_ENV, None)
            self.assertIsNone(read_run_trigger(LIFECYCLE_MONITOR_RUN_TRIGGER_ENV))


class PresentRunTriggerTests(unittest.TestCase):
    def test_present_run_trigger_labels(self) -> None:
        from monitor_display import present_run_trigger

        self.assertEqual(present_run_trigger("manual"), "Manual")
        self.assertEqual(present_run_trigger("scheduled"), "Scheduled")
        self.assertEqual(present_run_trigger(None), "—")
        self.assertEqual(present_run_trigger("cli"), "—")


class RunTriggerPersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        import paths

        self._env_patch = {
            "SQLITE_ENABLED": os.environ.get("SQLITE_ENABLED"),
            "AI_JOB_AGENT_DB_PATH": os.environ.get("AI_JOB_AGENT_DB_PATH"),
        }
        test_dir = paths.ensure_data_dir() / ".test_dbs"
        test_dir.mkdir(parents=True, exist_ok=True)
        self._db_path = test_dir / f"run_trigger_{os.getpid()}_{id(self)}.db"
        if self._db_path.exists():
            self._db_path.unlink()
        os.environ["AI_JOB_AGENT_DB_PATH"] = str(self._db_path)
        os.environ["SQLITE_ENABLED"] = "1"
        _clear_db_caches()

    def tearDown(self) -> None:
        _clear_db_caches()
        if self._db_path.exists():
            self._db_path.unlink()
        for key, value in self._env_patch.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_open_monitor_run_persists_manual_trigger(self) -> None:
        from db.bootstrap import ensure_database_ready
        from db.engine import get_session
        from db.models.schema import LifecycleMonitorRun
        from db.services.lifecycle_monitor import open_monitor_run
        from agent.run_trigger import LIFECYCLE_MONITOR_RUN_TRIGGER_ENV

        ensure_database_ready()
        now = datetime.now(UTC).replace(tzinfo=None)
        with patch.dict(os.environ, {LIFECYCLE_MONITOR_RUN_TRIGGER_ENV: "manual"}, clear=False):
            with get_session() as session:
                run = open_monitor_run(session, started_at=now)
                session.commit()
                run_id = int(run.id)

        with get_session() as session:
            row = session.get(LifecycleMonitorRun, run_id)
            assert row is not None
            self.assertEqual(row.run_trigger, "manual")

    def test_upsert_acquisition_run_persists_scheduled_trigger(self) -> None:
        from db.bootstrap import ensure_database_ready
        from db.engine import get_session
        from db.models.schema import AcquisitionRun
        from db.services.dual_write import DualWriteContext, _upsert_acquisition_runs
        from agent.run_trigger import ACQUISITION_RUN_TRIGGER_ENV

        ensure_database_ready()
        now = datetime.now(UTC).replace(tzinfo=None)
        ctx = DualWriteContext(
            run_started_at=now,
            run_completed_at=now,
            run_status="completed",
            run_notes="phase_c_runtime_dual_write",
        )
        with patch.dict(os.environ, {ACQUISITION_RUN_TRIGGER_ENV: "scheduled"}, clear=False):
            with get_session() as session:
                run_id = _upsert_acquisition_runs(session, ctx)
                session.commit()

        with get_session() as session:
            row = session.get(AcquisitionRun, run_id)
            assert row is not None
            self.assertEqual(row.run_trigger, "scheduled")


if __name__ == "__main__":
    unittest.main()
