"""Tests for AI refresh run persistence."""

from __future__ import annotations

import os
import sys
import unittest
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select, text

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
for entry in (str(_REPO_ROOT), str(_SRC)):
    if entry not in sys.path:
        sys.path.insert(0, entry)


def _clear_db_caches() -> None:
    from db.engine import get_engine, get_session_factory

    get_engine.cache_clear()
    get_session_factory.cache_clear()


class AiRefreshWriteTests(unittest.TestCase):
    def setUp(self) -> None:
        import paths

        self._env_patch = {
            "SQLITE_ENABLED": os.environ.get("SQLITE_ENABLED"),
            "AI_JOB_AGENT_DB_PATH": os.environ.get("AI_JOB_AGENT_DB_PATH"),
        }
        test_dir = paths.ensure_data_dir() / ".test_dbs"
        test_dir.mkdir(parents=True, exist_ok=True)
        self._db_path = test_dir / f"ai_refresh_write_{os.getpid()}_{id(self)}.db"
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

    def _seed_job(self, job_key_v2: str, *, ai_status: str = "pending") -> int:
        from db.bootstrap import ensure_database_ready
        from db.engine import get_session
        from db.models.schema import AiEvaluation, Job

        ensure_database_ready()
        now = datetime.now(UTC).replace(tzinfo=None)
        with get_session() as session:
            job = Job(
                job_key="pm::co",
                job_key_v2=job_key_v2,
                title="PM",
                company="Co",
                source="linkedin",
                created_at=now,
                updated_at=now,
            )
            session.add(job)
            session.flush()
            if ai_status:
                session.add(
                    AiEvaluation(
                        job_id=job.id,
                        ai_status=ai_status,
                        ai_score=7.0 if ai_status == "scored" else None,
                        reason="old reason" if ai_status == "scored" else "",
                        model="runtime_dual_write",
                        evaluated_at=now,
                    )
                )
            session.commit()
            return int(job.id)

    def test_insert_scored_evaluations_appends_row(self) -> None:
        from db.bootstrap import ensure_database_ready
        from db.engine import get_session
        from db.models.schema import AiEvaluation
        from db.services.ai_refresh_write import (
            finalize_ai_refresh_run,
            insert_scored_evaluations,
            open_ai_refresh_run,
        )

        job_key_v2 = "v2:refresh:append"
        self._seed_job(job_key_v2, ai_status="scored")
        ensure_database_ready()
        run_id = open_ai_refresh_run("discovery")

        with get_session() as session:
            result = insert_scored_evaluations(
                session,
                ai_refresh_run_id=run_id,
                jobs=[
                    {
                        "JOB_KEY_V2": job_key_v2,
                        "ai_status": "scored",
                        "score": 9.0,
                        "reason": "Updated profile match.",
                    }
                ],
            )
            session.commit()
            self.assertEqual(result.persisted, 1)
            self.assertEqual(result.skipped, 0)
            rows = session.execute(
                select(AiEvaluation).where(AiEvaluation.job_id.is_not(None))
            ).scalars().all()
            self.assertEqual(len(rows), 2)

        finalize_ai_refresh_run(
            run_id,
            status="completed",
            cohort_size=1,
            eligible_count=1,
            scored_count=1,
        )

        with get_session() as session:
            latest = session.execute(
                text(
                    """
                    SELECT ai_score, reason, model
                    FROM latest_ai_evaluations_view
                    WHERE job_key_v2 = :key
                    """
                ),
                {"key": job_key_v2},
            ).mappings().one()
            self.assertEqual(float(latest["ai_score"]), 9.0)
            self.assertEqual(latest["reason"], "Updated profile match.")
            self.assertEqual(latest["model"], "ai_refresh")

    def test_not_required_not_clobbered(self) -> None:
        from db.bootstrap import ensure_database_ready
        from db.engine import get_session
        from db.models.schema import AiEvaluation
        from db.services.ai_refresh_write import insert_scored_evaluations, open_ai_refresh_run

        job_key_v2 = "v2:refresh:notreq"
        self._seed_job(job_key_v2, ai_status="not_required")
        ensure_database_ready()
        run_id = open_ai_refresh_run("backlog")

        with get_session() as session:
            result = insert_scored_evaluations(
                session,
                ai_refresh_run_id=run_id,
                jobs=[
                    {
                        "JOB_KEY_V2": job_key_v2,
                        "ai_status": "scored",
                        "score": 9.0,
                        "reason": "Should not apply.",
                    }
                ],
            )
            session.commit()
            self.assertEqual(result.persisted, 0)
            self.assertEqual(result.skipped, 1)
            rows = session.execute(
                select(AiEvaluation).where(AiEvaluation.job_id.is_not(None))
            ).scalars().all()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].ai_status, "not_required")

    def test_resolved_score_prefers_orchestrator_score_over_stale_ai_score(self) -> None:
        from db.bootstrap import ensure_database_ready
        from db.engine import get_session
        from db.services.ai_refresh_write import insert_scored_evaluations, open_ai_refresh_run

        job_key_v2 = "v2:refresh:score-priority"
        self._seed_job(job_key_v2, ai_status="scored")
        ensure_database_ready()
        run_id = open_ai_refresh_run("discovery")

        with get_session() as session:
            result = insert_scored_evaluations(
                session,
                ai_refresh_run_id=run_id,
                jobs=[
                    {
                        "JOB_KEY_V2": job_key_v2,
                        "ai_status": "scored",
                        "ai_score": float("nan"),
                        "score": 8.0,
                        "reason": "Fresh orchestrator score.",
                    }
                ],
            )
            session.commit()
            self.assertEqual(result.persisted, 1)
            self.assertEqual(result.skipped, 0)


if __name__ == "__main__":
    unittest.main()
