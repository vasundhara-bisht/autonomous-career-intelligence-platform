"""Tests for monitor cohort resolution SQL (T1A)."""

from __future__ import annotations

import os
import sys
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


class MonitorCohortPredicateTests(unittest.TestCase):
    def test_classify_check_failure_infrastructure(self) -> None:
        from db.services.lifecycle_cohort import (
            classify_check_failure_class,
            is_infrastructure_check_failed,
        )

        self.assertTrue(is_infrastructure_check_failed("timeout:goto"))
        self.assertTrue(is_infrastructure_check_failed("fetch:network"))
        self.assertEqual(classify_check_failure_class("timeout:goto"), "infrastructure")
        self.assertEqual(classify_check_failure_class("fetch:network"), "infrastructure")

    def test_classify_check_failure_provider(self) -> None:
        from db.services.lifecycle_cohort import classify_check_failure_class

        self.assertEqual(classify_check_failure_class("auth:login_wall"), "provider")
        self.assertEqual(classify_check_failure_class("dom:no_apply_signal"), "provider")

    def test_classify_check_failure_ambiguous(self) -> None:
        from db.services.lifecycle_cohort import classify_check_failure_class

        self.assertEqual(classify_check_failure_class(None), "ambiguous")
        self.assertEqual(classify_check_failure_class("invalid_url:empty"), "ambiguous")

    def test_discovery_linkedin_open_in_cohort(self) -> None:
        from db.services.lifecycle_cohort import is_in_monitor_cohort

        self.assertTrue(
            is_in_monitor_cohort(
                pipeline_stage="New",
                source="linkedin",
                link="https://www.linkedin.com/jobs/view/1",
                listing_status="open",
                consecutive_check_failures=0,
                listing_check_paused_at=None,
            )
        )

    def test_user_managed_excluded(self) -> None:
        from db.services.lifecycle_cohort import is_in_monitor_cohort

        self.assertFalse(
            is_in_monitor_cohort(
                pipeline_stage="Applied",
                source="linkedin",
                link="https://www.linkedin.com/jobs/view/1",
                listing_status="open",
                consecutive_check_failures=0,
                listing_check_paused_at=None,
            )
        )

    def test_unmonitored_source_excluded(self) -> None:
        from db.services.lifecycle_cohort import is_in_monitor_cohort

        self.assertFalse(
            is_in_monitor_cohort(
                pipeline_stage="New",
                source="greenhouse",
                link="https://boards.greenhouse.io/acme/jobs/1",
                listing_status="open",
                consecutive_check_failures=0,
                listing_check_paused_at=None,
            )
        )

    def test_closed_excluded(self) -> None:
        from db.services.lifecycle_cohort import is_in_monitor_cohort

        self.assertFalse(
            is_in_monitor_cohort(
                pipeline_stage="New",
                source="linkedin",
                link="https://www.linkedin.com/jobs/view/1",
                listing_status="closed",
                consecutive_check_failures=0,
                listing_check_paused_at=None,
            )
        )

    def test_paused_check_failed_excluded(self) -> None:
        from db.listing_status import CHECK_FAILED_MAX_CONSECUTIVE
        from db.services.lifecycle_cohort import is_in_monitor_cohort

        self.assertFalse(
            is_in_monitor_cohort(
                pipeline_stage="New",
                source="instahyre",
                link="https://www.instahyre.com/job/1",
                listing_status="check_failed",
                consecutive_check_failures=CHECK_FAILED_MAX_CONSECUTIVE,
                listing_check_paused_at=datetime.now(UTC),
            )
        )

    def test_retryable_check_failed_in_cohort(self) -> None:
        from db.services.lifecycle_cohort import is_in_monitor_cohort

        self.assertTrue(
            is_in_monitor_cohort(
                pipeline_stage="Saved",
                source="instahyre",
                link="https://www.instahyre.com/job/2",
                listing_status="check_failed",
                listing_status_reason="timeout:goto",
                consecutive_check_failures=2,
                listing_check_paused_at=None,
            )
        )

    def test_provider_class_check_failed_excluded(self) -> None:
        from db.services.lifecycle_cohort import is_in_monitor_cohort

        self.assertFalse(
            is_in_monitor_cohort(
                pipeline_stage="New",
                source="linkedin",
                link="https://www.linkedin.com/jobs/view/1",
                listing_status="check_failed",
                listing_status_reason="dom:no_apply_signal",
                consecutive_check_failures=1,
                listing_check_paused_at=None,
            )
        )

    def test_empty_link_excluded(self) -> None:
        from db.services.lifecycle_cohort import is_in_monitor_cohort

        self.assertFalse(
            is_in_monitor_cohort(
                pipeline_stage="New",
                source="linkedin",
                link="  ",
                listing_status="open",
                consecutive_check_failures=0,
                listing_check_paused_at=None,
            )
        )


class MonitorCohortSqlIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        import paths

        self._env_patch = {
            "SQLITE_ENABLED": os.environ.get("SQLITE_ENABLED"),
            "AI_JOB_AGENT_DB_PATH": os.environ.get("AI_JOB_AGENT_DB_PATH"),
        }
        test_dir = paths.ensure_data_dir() / ".test_dbs"
        test_dir.mkdir(parents=True, exist_ok=True)
        self._db_path = test_dir / f"lifecycle_cohort_{os.getpid()}_{id(self)}.db"
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

    def _add_job(
        self,
        session,
        *,
        job_key_v2: str,
        source: str = "linkedin",
        pipeline_stage: str = "New",
        listing_status: str = "open",
        link: str = "https://www.linkedin.com/jobs/view/1",
        consecutive_check_failures: int = 0,
        listing_check_paused_at: datetime | None = None,
        listing_checked_at: datetime | None = None,
        listing_status_reason: str | None = None,
        listing_check_attempted_at: datetime | None = None,
        first_seen: datetime | None = None,
    ) -> int:
        from db.models.schema import AcquisitionRun, Job, JobObservation, UserJobState

        job = Job(
            job_key=f"k::{job_key_v2}",
            job_key_v2=job_key_v2,
            title="PM",
            company="Acme",
            source=source,
            link=link,
            listing_status=listing_status,
            listing_status_reason=listing_status_reason,
            consecutive_check_failures=consecutive_check_failures,
            listing_check_paused_at=listing_check_paused_at,
            listing_checked_at=listing_checked_at,
            listing_check_attempted_at=listing_check_attempted_at,
        )
        session.add(job)
        session.flush()
        session.add(
            UserJobState(
                job_id=job.id,
                applied=False,
                rejected=False,
                interview=False,
                offer=False,
                pipeline_stage=pipeline_stage,
                updated_at=datetime.now(UTC).replace(tzinfo=None),
            )
        )
        if first_seen is not None:
            run = AcquisitionRun(
                started_at=first_seen,
                completed_at=first_seen,
                status="completed",
            )
            session.add(run)
            session.flush()
            session.add(
                JobObservation(
                    job_id=job.id,
                    run_id=run.id,
                    observed_at=first_seen,
                    times_seen=1,
                )
            )
        session.flush()
        return int(job.id)

    def test_resolve_cohort_orders_open_before_check_failed(self) -> None:
        from db.bootstrap import ensure_database_ready
        from db.engine import get_session
        from db.services.lifecycle_cohort import resolve_monitor_cohort

        ensure_database_ready()
        reference = datetime(2026, 6, 16, 12, 0, 0)
        checked = datetime(2026, 6, 1, 12, 0, 0)

        with get_session() as session:
            self._add_job(session, job_key_v2="v2:open-old", listing_checked_at=checked)
            self._add_job(
                session,
                job_key_v2="v2:retry",
                listing_status="check_failed",
                listing_status_reason="timeout:goto",
                consecutive_check_failures=1,
                listing_check_attempted_at=checked,
            )
            self._add_job(
                session,
                job_key_v2="v2:applied",
                pipeline_stage="Applied",
                listing_status="monitor_exempt",
            )
            self._add_job(
                session,
                job_key_v2="v2:gh",
                source="greenhouse",
                link="https://boards.greenhouse.io/x/jobs/1",
            )
            session.commit()

        with get_session() as session:
            cohort = resolve_monitor_cohort(session, reference_at=reference)

        keys = [row.job_key_v2 for row in cohort]
        self.assertEqual(keys, ["v2:open-old", "v2:retry"])
        self.assertNotIn("v2:applied", keys)
        self.assertNotIn("v2:gh", keys)

    def test_resolve_cohort_excludes_provider_class_check_failed(self) -> None:
        from db.bootstrap import ensure_database_ready
        from db.engine import get_session
        from db.services.lifecycle_cohort import resolve_monitor_cohort

        ensure_database_ready()
        reference = datetime(2026, 6, 16, 12, 0, 0)
        attempted = datetime(2026, 6, 1, 12, 0, 0)

        with get_session() as session:
            self._add_job(
                session,
                job_key_v2="v2:infra",
                listing_status="check_failed",
                listing_status_reason="timeout:goto",
                consecutive_check_failures=1,
                listing_check_attempted_at=attempted,
            )
            self._add_job(
                session,
                job_key_v2="v2:provider",
                link="https://www.linkedin.com/jobs/view/2",
                listing_status="check_failed",
                listing_status_reason="dom:no_apply_signal",
                consecutive_check_failures=1,
                listing_check_attempted_at=attempted,
            )
            session.commit()

        with get_session() as session:
            cohort = resolve_monitor_cohort(session, reference_at=reference)

        keys = [row.job_key_v2 for row in cohort]
        self.assertEqual(keys, ["v2:infra"])
        self.assertNotIn("v2:provider", keys)

    def test_resolve_cohort_orders_t0_before_t1_and_t4_last(self) -> None:
        from db.bootstrap import ensure_database_ready
        from db.engine import get_session
        from db.services.lifecycle_cohort import resolve_monitor_cohort

        ensure_database_ready()
        reference = datetime(2026, 6, 16, 12, 0, 0)
        young_seen = datetime(2026, 6, 10, 12, 0, 0)
        old_checked = datetime(2026, 6, 1, 12, 0, 0)
        recent_checked = datetime(2026, 6, 15, 12, 0, 0)

        with get_session() as session:
            self._add_job(session, job_key_v2="v2:t0-new")
            self._add_job(
                session,
                job_key_v2="v2:t1-young",
                listing_checked_at=old_checked,
                first_seen=young_seen,
            )
            self._add_job(
                session,
                job_key_v2="v2:t4-infra",
                listing_status="check_failed",
                listing_status_reason="browser:not_started",
                consecutive_check_failures=1,
                listing_check_attempted_at=old_checked,
            )
            self._add_job(
                session,
                job_key_v2="v2:not-due",
                listing_checked_at=recent_checked,
                first_seen=young_seen,
            )
            session.commit()

        with get_session() as session:
            cohort = resolve_monitor_cohort(session, reference_at=reference)

        keys = [row.job_key_v2 for row in cohort]
        self.assertEqual(keys, ["v2:t0-new", "v2:t1-young", "v2:t4-infra"])
        self.assertNotIn("v2:not-due", keys)

    def test_resolve_cohort_limit(self) -> None:
        from db.bootstrap import ensure_database_ready
        from db.engine import get_session
        from db.services.lifecycle_cohort import resolve_monitor_cohort

        ensure_database_ready()

        with get_session() as session:
            for idx in range(5):
                self._add_job(session, job_key_v2=f"v2:lim:{idx}")
            session.commit()

        with get_session() as session:
            cohort = resolve_monitor_cohort(session, limit=2)

        self.assertEqual(len(cohort), 2)

    def test_count_monitor_candidates_by_source(self) -> None:
        from db.bootstrap import ensure_database_ready
        from db.engine import get_session
        from db.services.lifecycle_cohort import count_monitor_candidates_by_source

        ensure_database_ready()
        reference = datetime(2026, 6, 16, 12, 0, 0)

        with get_session() as session:
            self._add_job(session, job_key_v2="v2:li-queue", source="linkedin")
            self._add_job(
                session,
                job_key_v2="v2:ih-queue",
                source="instahyre",
                link="https://www.instahyre.com/job-abc-1/",
            )
            self._add_job(
                session,
                job_key_v2="v2:ih-applied",
                source="instahyre",
                link="https://www.instahyre.com/job-abc-2/",
                pipeline_stage="Applied",
                listing_status="monitor_exempt",
            )
            session.commit()

        with get_session() as session:
            linkedin_count = count_monitor_candidates_by_source(
                session,
                "linkedin",
                reference_at=reference,
            )
            instahyre_count = count_monitor_candidates_by_source(
                session,
                "instahyre",
                reference_at=reference,
            )

        self.assertEqual(linkedin_count, 1)
        self.assertEqual(instahyre_count, 1)

    def test_historical_view_exposes_listing_columns(self) -> None:
        from db.bootstrap import ensure_database_ready
        from db.engine import get_session
        from db.read.contracts import HISTORICAL_VIEW_COLUMNS
        from sqlalchemy import text

        ensure_database_ready()

        with get_session() as session:
            self._add_job(session, job_key_v2="v2:view-listing")
            session.commit()

        with get_session() as session:
            row = session.execute(
                text(
                    "SELECT listing_status, consecutive_check_failures "
                    "FROM historical_jobs_view WHERE JOB_KEY_V2 = 'v2:view-listing'"
                )
            ).mappings().one()

        self.assertEqual(row["listing_status"], "open")
        self.assertEqual(int(row["consecutive_check_failures"]), 0)
        for col in (
            "listing_status",
            "listing_status_reason",
            "listing_checked_at",
            "listing_check_attempted_at",
            "listing_closed_at",
            "listing_removed_at",
            "consecutive_check_failures",
            "listing_check_paused_at",
        ):
            self.assertIn(col, HISTORICAL_VIEW_COLUMNS)


if __name__ == "__main__":
    unittest.main()
