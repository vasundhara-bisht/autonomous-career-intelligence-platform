"""Tests for acquisition / AI refresh evaluation isolation."""

from __future__ import annotations

import os
import sys
import unittest
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
for entry in (str(_REPO_ROOT), str(_SRC)):
    if entry not in sys.path:
        sys.path.insert(0, entry)


def _clear_db_caches() -> None:
    from db.engine import get_engine, get_session_factory

    get_engine.cache_clear()
    get_session_factory.cache_clear()


class AiRefreshDualWriteIsolationTests(unittest.TestCase):
    def setUp(self) -> None:
        import paths

        self._env_patch = {
            "SQLITE_ENABLED": os.environ.get("SQLITE_ENABLED"),
            "AI_JOB_AGENT_DB_PATH": os.environ.get("AI_JOB_AGENT_DB_PATH"),
        }
        test_dir = paths.ensure_data_dir() / ".test_dbs"
        test_dir.mkdir(parents=True, exist_ok=True)
        self._db_path = test_dir / f"ai_refresh_isolation_{os.getpid()}_{id(self)}.db"
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

    def test_dual_write_appends_when_latest_eval_is_ai_refresh(self) -> None:
        from db.bootstrap import ensure_database_ready
        from db.engine import get_session
        from db.models.schema import AcquisitionRun, AiEvaluation, AiRefreshRun, Job
        from db.services.ai_refresh_write import insert_scored_evaluations
        from db.services.dual_write import _upsert_ai_evaluations

        ensure_database_ready()
        now = datetime.now(UTC).replace(tzinfo=None)
        with get_session() as session:
            job = Job(
                job_key="pm::co",
                job_key_v2="v2:isolation:1",
                title="PM",
                company="Co",
                source="linkedin",
                created_at=now,
                updated_at=now,
            )
            session.add(job)
            session.flush()
            refresh_run = AiRefreshRun(
                started_at=now,
                status="completed",
                preset="discovery",
            )
            session.add(refresh_run)
            session.flush()
            insert_scored_evaluations(
                session,
                ai_refresh_run_id=int(refresh_run.id),
                jobs=[
                    {
                        "JOB_KEY_V2": "v2:isolation:1",
                        "ai_status": "scored",
                        "score": 9.0,
                        "reason": "Refresh eval.",
                    }
                ],
            )
            session.commit()
            job_id = int(job.id)
            refresh_run_id = int(refresh_run.id)

        with get_session() as session:
            acq_run = AcquisitionRun(started_at=now, status="completed")
            session.add(acq_run)
            session.commit()
            acq_run_id = int(acq_run.id)
            _upsert_ai_evaluations(
                session,
                run_id=acq_run_id,
                jobs=[
                    {
                        "JOB_KEY_V2": "v2:isolation:1",
                        "ai_status": "scored",
                        "score": 7.0,
                        "reason": "Acquisition eval.",
                    }
                ],
                job_id_by_v2={"v2:isolation:1": job_id},
            )
            session.commit()
            rows = session.execute(
                select(AiEvaluation).where(AiEvaluation.job_id == job_id).order_by(AiEvaluation.id)
            ).scalars().all()
            self.assertEqual(len(rows), 2)
            refresh_row = next(row for row in rows if row.model == "ai_refresh")
            acq_row = next(row for row in rows if row.model == "runtime_dual_write")
            self.assertEqual(int(refresh_row.ai_refresh_run_id or 0), refresh_run_id)
            self.assertIsNone(acq_row.ai_refresh_run_id)
            self.assertEqual(int(acq_row.run_id or 0), acq_run_id)


if __name__ == "__main__":
    unittest.main()
