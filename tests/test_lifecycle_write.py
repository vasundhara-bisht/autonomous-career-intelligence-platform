"""Unit and integration tests for lifecycle listing write service (T1A)."""

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


class LifecycleWriteValidationTests(unittest.TestCase):
    def test_terminal_closed_rejects_scheduler_b_write(self) -> None:
        from db.services.lifecycle_write import validate_scheduler_b_transition

        result = validate_scheduler_b_transition("closed", "open")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertTrue(result.skipped)
        self.assertEqual(result.skip_reason, "terminal_state")

    def test_terminal_removed_rejects_scheduler_b_write(self) -> None:
        from db.services.lifecycle_write import validate_scheduler_b_transition

        result = validate_scheduler_b_transition("removed", "check_failed")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.skip_reason, "terminal_state")

    def test_invalid_target_status_rejected(self) -> None:
        from db.services.lifecycle_write import validate_scheduler_b_transition

        result = validate_scheduler_b_transition("open", "monitor_exempt")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.skip_reason, "invalid_target_status")


class LifecycleWriteIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        import paths

        self._env_patch = {
            "SQLITE_ENABLED": os.environ.get("SQLITE_ENABLED"),
            "AI_JOB_AGENT_DB_PATH": os.environ.get("AI_JOB_AGENT_DB_PATH"),
        }
        test_dir = paths.ensure_data_dir() / ".test_dbs"
        test_dir.mkdir(parents=True, exist_ok=True)
        self._db_path = test_dir / f"lifecycle_write_{os.getpid()}_{id(self)}.db"
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

    def _create_job(self, session, *, job_key_v2: str, listing_status: str = "open") -> int:
        from db.models.schema import Job

        job = Job(
            job_key=f"k::{job_key_v2}",
            job_key_v2=job_key_v2,
            title="PM",
            company="Acme",
            source="linkedin",
            link="https://www.linkedin.com/jobs/view/123",
            listing_status=listing_status,
        )
        session.add(job)
        session.flush()
        return int(job.id)

    def test_successful_open_resets_failure_counters(self) -> None:
        from db.bootstrap import ensure_database_ready
        from db.engine import get_session
        from db.models.schema import Job
        from db.services.lifecycle_write import apply_scheduler_b_outcome

        ensure_database_ready()
        now = datetime.now(UTC).replace(tzinfo=None)

        with get_session() as session:
            job_id = self._create_job(session, job_key_v2="v2:open-reset")
            job = session.get(Job, job_id)
            assert job is not None
            job.consecutive_check_failures = 3
            session.commit()

        with get_session() as session:
            job = session.get(Job, job_id)
            assert job is not None
            result = apply_scheduler_b_outcome(
                session,
                job,
                listing_status="open",
                listing_status_reason=None,
                attempted_at=now,
                classification_succeeded=True,
            )
            session.commit()

        self.assertTrue(result.applied)
        with get_session() as session:
            job = session.get(Job, job_id)
            assert job is not None
            self.assertEqual(job.listing_status, "open")
            self.assertEqual(job.consecutive_check_failures, 0)
            self.assertIsNone(job.listing_check_paused_at)
            self.assertEqual(job.listing_checked_at, now)

    def test_check_failed_increments_counter_and_pauses_at_cap(self) -> None:
        from db.bootstrap import ensure_database_ready
        from db.engine import get_session
        from db.models.schema import Job
        from db.listing_status import CHECK_FAILED_MAX_CONSECUTIVE
        from db.services.lifecycle_write import apply_scheduler_b_outcome

        ensure_database_ready()
        now = datetime.now(UTC).replace(tzinfo=None)

        with get_session() as session:
            job_id = self._create_job(session, job_key_v2="v2:fail-cap")
            job = session.get(Job, job_id)
            assert job is not None
            job.consecutive_check_failures = CHECK_FAILED_MAX_CONSECUTIVE - 1
            session.commit()

        with get_session() as session:
            job = session.get(Job, job_id)
            assert job is not None
            apply_scheduler_b_outcome(
                session,
                job,
                listing_status="check_failed",
                listing_status_reason="timeout:goto_45s",
                attempted_at=now,
                classification_succeeded=False,
            )
            session.commit()

        with get_session() as session:
            job = session.get(Job, job_id)
            assert job is not None
            self.assertEqual(job.listing_status, "check_failed")
            self.assertEqual(job.consecutive_check_failures, CHECK_FAILED_MAX_CONSECUTIVE)
            self.assertEqual(job.listing_check_paused_at, now)
            self.assertIsNone(job.listing_checked_at)

    def test_first_closed_sets_terminal_timestamp_immutable(self) -> None:
        from db.bootstrap import ensure_database_ready
        from db.engine import get_session
        from db.models.schema import Job
        from db.services.lifecycle_write import apply_scheduler_b_outcome

        ensure_database_ready()
        first = datetime(2026, 6, 1, 10, 0, 0)
        later = datetime(2026, 6, 2, 10, 0, 0)

        with get_session() as session:
            job_id = self._create_job(session, job_key_v2="v2:closed-ts")
            session.commit()

        with get_session() as session:
            job = session.get(Job, job_id)
            assert job is not None
            apply_scheduler_b_outcome(
                session,
                job,
                listing_status="closed",
                listing_status_reason="closed:phrase",
                attempted_at=first,
                classification_succeeded=True,
            )
            session.commit()

        with get_session() as session:
            job = session.get(Job, job_id)
            assert job is not None
            self.assertEqual(job.listing_closed_at, first)
            skip = apply_scheduler_b_outcome(
                session,
                job,
                listing_status="open",
                listing_status_reason=None,
                attempted_at=later,
                classification_succeeded=True,
            )
            session.commit()

        self.assertTrue(skip.skipped)
        with get_session() as session:
            job = session.get(Job, job_id)
            assert job is not None
            self.assertEqual(job.listing_status, "closed")
            self.assertEqual(job.listing_closed_at, first)

    def test_set_monitor_exempt_idempotent(self) -> None:
        from db.bootstrap import ensure_database_ready
        from db.engine import get_session
        from db.models.schema import Job
        from db.services.lifecycle_write import set_monitor_exempt

        ensure_database_ready()

        with get_session() as session:
            job_id = self._create_job(session, job_key_v2="v2:exempt")
            session.commit()

        with get_session() as session:
            job = session.get(Job, job_id)
            assert job is not None
            first = set_monitor_exempt(session, job)
            session.commit()
            self.assertTrue(first.applied)

        with get_session() as session:
            job = session.get(Job, job_id)
            assert job is not None
            second = set_monitor_exempt(session, job)
            self.assertTrue(second.skipped)
            self.assertEqual(second.skip_reason, "already_monitor_exempt")

    def test_user_managed_pipeline_backfill_sql(self) -> None:
        """Mirrors §2.4 migration backfill for rows present before monitor runs."""
        from agent.pipeline_stages import USER_MANAGED_PIPELINE_STAGES
        from db.bootstrap import ensure_database_ready
        from db.engine import get_session
        from db.models.schema import Job, UserJobState
        from sqlalchemy import text

        ensure_database_ready()
        now = datetime.now(UTC).replace(tzinfo=None)
        stages_sql = ", ".join(f"'{s}'" for s in USER_MANAGED_PIPELINE_STAGES)

        with get_session() as session:
            job_id = self._create_job(session, job_key_v2="v2:applied-backfill")
            session.add(
                UserJobState(
                    job_id=job_id,
                    applied=True,
                    rejected=False,
                    interview=False,
                    offer=False,
                    pipeline_stage="Applied",
                    updated_at=now,
                )
            )
            session.flush()
            session.execute(
                text(
                    f"""
                    UPDATE jobs
                    SET listing_status = 'monitor_exempt'
                    WHERE id IN (
                        SELECT u.job_id FROM user_job_state u
                        WHERE COALESCE(u.pipeline_stage, 'New') IN ({stages_sql})
                    )
                    """
                )
            )
            session.commit()

        with get_session() as session:
            job = session.execute(
                select(Job).where(Job.job_key_v2 == "v2:applied-backfill")
            ).scalar_one()
            self.assertEqual(job.listing_status, "monitor_exempt")


if __name__ == "__main__":
    unittest.main()
