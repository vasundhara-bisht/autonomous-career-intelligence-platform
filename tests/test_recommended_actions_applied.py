"""Tests for Phase 3A.1 — Applied quick action from Recommended Actions."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from sqlalchemy import select

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DASHBOARD = _REPO_ROOT / "dashboard"
_SRC = _REPO_ROOT / "src"
for entry in (str(_REPO_ROOT), str(_DASHBOARD), str(_SRC)):
    if entry not in sys.path:
        sys.path.insert(0, entry)


def _clear_db_caches() -> None:
    from db.engine import get_engine, get_session_factory

    get_engine.cache_clear()
    get_session_factory.cache_clear()


def _iso_days_ago(days: int, *, reference: date) -> str:
    return (reference - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")


def _job_row(
    *,
    key: str = "job-1",
    stage: str = "New",
    score: float = 8.0,
    ai_status: str = "scored",
    first_seen_days_ago: int = 2,
    currently_active: bool = True,
    reason: str = "Strong product fit",
    reference: date,
) -> dict:
    return {
        "JOB_KEY": key,
        "JOB_KEY_V2": f"v2:{key}",
        "title": f"Title {key}",
        "company": f"Company {key}",
        "pipeline_stage": stage,
        "is_ai_scored": ai_status == "scored",
        "ai_status": ai_status,
        "score": score,
        "first_seen": _iso_days_ago(first_seen_days_ago, reference=reference),
        "currently_active": currently_active,
        "reason": reason,
        "source": "instahyre",
        "link": "https://example.com/jobs/1",
    }


class RecommendedActionsAppliedTests(unittest.TestCase):
    def setUp(self) -> None:
        self.reference = date(2026, 6, 10)
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

    def _seed_job(self, *, v2: str = "v2:fresh", notes: str = "keep me") -> None:
        from db.bootstrap import ensure_database_ready
        from db.engine import get_session
        from db.models.schema import Job, UserJobState

        ensure_database_ready()
        now = datetime.now(UTC).replace(tzinfo=None)
        with get_session() as session:
            job = Job(
                job_key="fresh",
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
                    notes=notes,
                    updated_at=now,
                )
            )
            session.commit()

    def test_mark_job_applied_updates_user_job_state(self) -> None:
        from db.engine import get_session
        from db.models.schema import Job, UserJobState
        from db.services.dashboard_write import mark_job_applied

        self._seed_job()
        before = datetime.now(UTC).replace(tzinfo=None)
        self.assertTrue(
            mark_job_applied(job_key_v2="v2:fresh", job_key="fresh")
        )

        with get_session() as session:
            job = session.execute(
                select(Job).where(Job.job_key_v2 == "v2:fresh")
            ).scalar_one()
            state = session.get(UserJobState, job.id)
            assert state is not None
            self.assertEqual(state.pipeline_stage, "Applied")
            self.assertTrue(state.applied)
            self.assertFalse(state.rejected)
            self.assertFalse(state.interview)
            self.assertFalse(state.offer)
            self.assertEqual(state.notes, "keep me")
            self.assertGreaterEqual(state.updated_at, before)

    def test_mark_job_applied_returns_false_when_write_disabled(self) -> None:
        from db.services.dashboard_write import mark_job_applied

        self._seed_job()
        with patch.dict(os.environ, {"SQLITE_DASHBOARD_WRITE": "0"}, clear=False):
            _clear_db_caches()
            self.assertFalse(
                mark_job_applied(job_key_v2="v2:fresh", job_key="fresh")
            )

    def test_mark_job_applied_removes_job_from_apply_today_queue(self) -> None:
        from db.read.historical import load_historical_jobs_view_df
        from db.services.dashboard_write import mark_job_applied
        from recommended_actions import compute_recommended_actions

        self._seed_job()
        before_df = pd.DataFrame(
            [_job_row(key="fresh", reference=self.reference)]
        )
        before = compute_recommended_actions(before_df, reference_date=self.reference)
        self.assertEqual(before.apply_today_total, 1)

        self.assertTrue(
            mark_job_applied(job_key_v2="v2:fresh", job_key="fresh")
        )

        from db.bootstrap import ensure_database_ready
        from db.engine import get_session

        ensure_database_ready()
        with get_session() as session:
            hist = load_historical_jobs_view_df(session)
        row = hist[hist["JOB_KEY_V2"] == "v2:fresh"].iloc[0]
        self.assertEqual(str(row["pipeline_stage"]), "Applied")

        after_df = pd.DataFrame(
            [
                _job_row(
                    key="fresh",
                    stage="Applied",
                    reference=self.reference,
                )
            ]
        )
        after = compute_recommended_actions(after_df, reference_date=self.reference)
        self.assertEqual(after.apply_today_total, 0)

    def test_apply_today_action_includes_job_keys(self) -> None:
        from recommended_actions import compute_recommended_actions

        df = pd.DataFrame(
            [_job_row(key="fresh", reference=self.reference)]
        )
        result = compute_recommended_actions(df, reference_date=self.reference)
        self.assertEqual(result.apply_today_total, 1)
        action = result.apply_today[0]
        self.assertEqual(action.job_key, "fresh")
        self.assertEqual(action.job_key_v2, "v2:fresh")


if __name__ == "__main__":
    unittest.main()
