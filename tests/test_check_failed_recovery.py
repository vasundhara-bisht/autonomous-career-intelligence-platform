"""Tests for incident check_failed recovery (OHM Phase 6)."""

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


class CheckFailedRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        import paths

        self._env_patch = {
            "SQLITE_ENABLED": os.environ.get("SQLITE_ENABLED"),
            "AI_JOB_AGENT_DB_PATH": os.environ.get("AI_JOB_AGENT_DB_PATH"),
        }
        test_dir = paths.ensure_data_dir() / ".test_dbs"
        test_dir.mkdir(parents=True, exist_ok=True)
        self._db_path = test_dir / f"check_failed_recovery_{os.getpid()}_{id(self)}.db"
        if self._db_path.exists():
            self._db_path.unlink()
        os.environ["AI_JOB_AGENT_DB_PATH"] = str(self._db_path)
        os.environ["SQLITE_ENABLED"] = "1"
        from db.engine import get_engine, get_session_factory

        get_engine.cache_clear()
        get_session_factory.cache_clear()
        from db.bootstrap import ensure_database_ready

        ensure_database_ready()

    def tearDown(self) -> None:
        from db.engine import get_engine, get_session_factory

        get_engine.cache_clear()
        get_session_factory.cache_clear()
        for key, value in self._env_patch.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        if self._db_path.exists():
            self._db_path.unlink()

    def test_is_incident_misclassified_reason(self) -> None:
        from db.services.check_failed_recovery import is_incident_misclassified_check_failed

        self.assertTrue(is_incident_misclassified_check_failed("auth:login_wall"))
        self.assertTrue(is_incident_misclassified_check_failed("dom:no_apply_signal"))
        self.assertFalse(is_incident_misclassified_check_failed("timeout:goto"))

    def test_reset_incident_jobs_dry_run_and_apply(self) -> None:
        from db.engine import get_session
        from db.models.schema import Job
        from db.services.check_failed_recovery import reset_incident_check_failed_jobs

        now = datetime.now(UTC).replace(tzinfo=None)
        with get_session() as session:
            session.add(
                Job(
                    job_key="legacy-key-1",
                    job_key_v2="linkedin|incident|1",
                    source="linkedin",
                    title="A",
                    company="Co",
                    link="https://example.com/1",
                    listing_status="check_failed",
                    listing_status_reason="dom:no_apply_signal",
                    consecutive_check_failures=3,
                    created_at=now,
                    updated_at=now,
                )
            )
            session.add(
                Job(
                    job_key="legacy-key-2",
                    job_key_v2="linkedin|infra|1",
                    source="linkedin",
                    title="B",
                    company="Co",
                    link="https://example.com/2",
                    listing_status="check_failed",
                    listing_status_reason="timeout:goto",
                    consecutive_check_failures=1,
                    created_at=now,
                    updated_at=now,
                )
            )
            session.commit()

            dry = reset_incident_check_failed_jobs(session, source="linkedin", dry_run=True)
            self.assertEqual(dry.matched, 1)
            self.assertEqual(dry.reset, 0)

            applied = reset_incident_check_failed_jobs(session, source="linkedin", dry_run=False)
            session.commit()
            self.assertEqual(applied.reset, 1)

            jobs = (
                session.query(Job)
                .filter(Job.source == "linkedin")
                .order_by(Job.job_key_v2.asc())
                .all()
            )
            self.assertEqual(len(jobs), 2)
            incident, infra = jobs
            self.assertEqual(incident.listing_status, "open")
            self.assertIsNone(incident.listing_status_reason)
            self.assertEqual(incident.consecutive_check_failures, 0)
            self.assertEqual(infra.listing_status, "check_failed")
            self.assertEqual(infra.listing_status_reason, "timeout:goto")


if __name__ == "__main__":
    unittest.main()
