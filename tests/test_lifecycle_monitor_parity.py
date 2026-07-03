"""Tests for TD9 listing lifecycle parity checks."""

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


class ListingLifecycleParityTests(unittest.TestCase):
    def setUp(self) -> None:
        import paths

        self._env_patch = {
            "SQLITE_ENABLED": os.environ.get("SQLITE_ENABLED"),
            "AI_JOB_AGENT_DB_PATH": os.environ.get("AI_JOB_AGENT_DB_PATH"),
        }
        test_dir = paths.ensure_data_dir() / ".test_dbs"
        test_dir.mkdir(parents=True, exist_ok=True)
        self._db_path = test_dir / f"lifecycle_parity_{os.getpid()}_{id(self)}.db"
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

    def test_null_listing_status_emits_warning(self) -> None:
        from db.bootstrap import ensure_database_ready
        from db.engine import get_session
        from db.models.schema import Job
        from db.services.parity_checks import check_listing_lifecycle_parity

        ensure_database_ready()
        with get_session() as session:
            job = Job(
                job_key="k::bad",
                job_key_v2="v2:bad",
                title="PM",
                company="Acme",
                source="linkedin",
                link="https://www.linkedin.com/jobs/view/1/",
            )
            session.add(job)
            session.flush()
            from sqlalchemy import text

            session.execute(
                text("UPDATE jobs SET listing_status = '' WHERE id = :job_id"),
                {"job_id": int(job.id)},
            )
            session.commit()

        with get_session() as session:
            report = check_listing_lifecycle_parity(session)

        self.assertGreaterEqual(report.warning_count, 1)
        self.assertTrue(any("NULL/empty" in w for w in report.warnings))

    def test_illegal_closed_reopen_emits_warning(self) -> None:
        from db.bootstrap import ensure_database_ready
        from db.engine import get_session
        from db.models.schema import Job
        from db.services.parity_checks import check_listing_lifecycle_parity

        ensure_database_ready()
        now = datetime.now(UTC).replace(tzinfo=None)
        with get_session() as session:
            job = Job(
                job_key="k::reopen",
                job_key_v2="v2:reopen",
                title="PM",
                company="Acme",
                source="linkedin",
                link="https://www.linkedin.com/jobs/view/2/",
                listing_status="open",
                listing_closed_at=now,
            )
            session.add(job)
            session.commit()

        with get_session() as session:
            report = check_listing_lifecycle_parity(session)

        self.assertTrue(any("illegal closed→open" in w for w in report.warnings))

    def test_validate_script_always_exits_zero(self) -> None:
        from db.bootstrap import ensure_database_ready
        from scripts.validate_lifecycle_monitor_parity import main

        ensure_database_ready()
        self.assertEqual(main([]), 0)

    def test_cohort_completeness_gap_warning(self) -> None:
        from db.bootstrap import ensure_database_ready
        from db.engine import get_session
        from db.models.schema import LifecycleMonitorRun
        from db.services.parity_checks import check_listing_lifecycle_parity

        ensure_database_ready()
        now = datetime.now(UTC).replace(tzinfo=None)
        with get_session() as session:
            run = LifecycleMonitorRun(
                started_at=now,
                completed_at=now,
                status="completed",
                cohort_size=5,
                checked_count=2,
            )
            session.add(run)
            session.commit()
            run_id = int(run.id)

        with get_session() as session:
            report = check_listing_lifecycle_parity(session, run_id=run_id)

        self.assertTrue(any("cohort completeness gap" in w for w in report.warnings))

    def test_zero_check_warning_uses_skipped_budget_status(self) -> None:
        from db.bootstrap import ensure_database_ready
        from db.engine import get_session
        from db.models.schema import Job, LifecycleMonitorRun
        from db.services.parity_checks import check_listing_lifecycle_parity

        ensure_database_ready()
        now = datetime.now(UTC).replace(tzinfo=None)
        with get_session() as session:
            session.add(
                Job(
                    job_key="k::due",
                    job_key_v2="v2:due",
                    title="PM",
                    company="Acme",
                    source="linkedin",
                    link="https://www.linkedin.com/jobs/view/9/",
                    listing_status="open",
                )
            )
            run = LifecycleMonitorRun(
                started_at=now,
                completed_at=now,
                status="skipped_budget_exhausted",
                cohort_size=0,
                checked_count=0,
            )
            session.add(run)
            session.commit()
            run_id = int(run.id)

        with get_session() as session:
            report = check_listing_lifecycle_parity(session, run_id=run_id)

        self.assertTrue(
            any(
                "skipped_budget_exhausted run_id=" in w and "checked_count=0" in w
                for w in report.warnings
            )
        )


if __name__ == "__main__":
    unittest.main()
