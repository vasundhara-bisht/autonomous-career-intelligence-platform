"""Tests for provider protection detection (OHM Phase 2)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
for entry in (str(_REPO_ROOT), str(_SRC)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load_fixture(name: str) -> str:
    return (_FIXTURES / name).read_text(encoding="utf-8")


class ProviderProtectionDetectionTests(unittest.TestCase):
    def test_unusual_activity_page_detected(self) -> None:
        from monitor.provider_protection import detect_linkedin_protection

        html = _load_fixture("linkedin_unusual_activity.html")
        result = detect_linkedin_protection(
            url="https://www.linkedin.com/checkpoint/challenge/verify",
            html=html,
            http_status=200,
        )
        self.assertTrue(result.is_protection)
        self.assertEqual(result.reason, "protection:unusual_activity")
        self.assertEqual(result.protection_type, "provider_protection")

    def test_normal_job_page_not_protection(self) -> None:
        from monitor.provider_protection import detect_linkedin_protection

        html = _load_fixture("linkedin_job_open_live_shell.html")
        result = detect_linkedin_protection(
            url="https://www.linkedin.com/jobs/view/4417376197/",
            html=html,
            http_status=200,
        )
        self.assertFalse(result.is_protection)

    def test_login_wall_without_job_shell_is_not_protection(self) -> None:
        from monitor.provider_protection import detect_linkedin_protection

        result = detect_linkedin_protection(
            url="https://www.linkedin.com/login",
            html="<html><body><h1>Sign in</h1><p>Join LinkedIn</p></body></html>",
            http_status=200,
        )
        self.assertFalse(result.is_protection)

    def test_fetch_error_is_not_protection(self) -> None:
        from monitor.provider_protection import detect_linkedin_protection

        result = detect_linkedin_protection(
            url="https://www.linkedin.com/jobs/view/1/",
            html="",
            http_status=None,
            error="timeout:goto",
        )
        self.assertFalse(result.is_protection)

    def test_rehab_challenge_structural_marker(self) -> None:
        from monitor.provider_protection import detect_linkedin_protection

        result = detect_linkedin_protection(
            url="https://www.linkedin.com/feed/",
            html='<html><body><form id="rehab-challenge"></form></body></html>',
            http_status=200,
        )
        self.assertTrue(result.is_protection)
        self.assertEqual(result.reason, "protection:checkpoint")


class ProviderStatePersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        import os

        import paths

        self._env_patch = {
            "SQLITE_ENABLED": os.environ.get("SQLITE_ENABLED"),
            "AI_JOB_AGENT_DB_PATH": os.environ.get("AI_JOB_AGENT_DB_PATH"),
        }
        test_dir = paths.ensure_data_dir() / ".test_dbs"
        test_dir.mkdir(parents=True, exist_ok=True)
        self._db_path = test_dir / f"provider_state_{os.getpid()}_{id(self)}.db"
        if self._db_path.exists():
            self._db_path.unlink()
        os.environ["AI_JOB_AGENT_DB_PATH"] = str(self._db_path)
        os.environ["SQLITE_ENABLED"] = "1"
        from db.engine import get_engine, get_session_factory

        get_engine.cache_clear()
        get_session_factory.cache_clear()

    def tearDown(self) -> None:
        import os

        from db.engine import get_engine, get_session_factory

        get_engine.cache_clear()
        get_session_factory.cache_clear()
        if self._db_path.exists():
            self._db_path.unlink()
        for key, value in self._env_patch.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_record_and_clear_provider_state(self) -> None:
        from datetime import UTC, datetime, timedelta

        from db.bootstrap import ensure_database_ready
        from db.engine import get_session
        from db.listing_status import PROVIDER_HEALTH_OK, PROVIDER_HEALTH_PROTECTION
        from db.services.provider_state import (
            clear_provider_state_on_recovery,
            get_provider_state,
            record_provider_protection,
        )

        ensure_database_ready()
        now = datetime.now(UTC).replace(tzinfo=None)

        with get_session() as session:
            record_provider_protection(
                session,
                source="linkedin",
                reason="protection:unusual_activity",
                detected_at=now,
                backoff_base_hours=6,
                backoff_max_hours=48,
            )
            session.commit()

        with get_session() as session:
            row = get_provider_state(session, "linkedin")
            assert row is not None
            self.assertEqual(row.health, PROVIDER_HEALTH_PROTECTION)
            self.assertEqual(row.reason, "protection:unusual_activity")
            self.assertEqual(row.consecutive_failures, 1)
            self.assertIsNotNone(row.backoff_until)
            self.assertEqual(row.backoff_until, now + timedelta(hours=6))

        with get_session() as session:
            clear_provider_state_on_recovery(
                session,
                source="linkedin",
                recovered_at=now,
            )
            session.commit()

        with get_session() as session:
            row = get_provider_state(session, "linkedin")
            assert row is not None
            self.assertEqual(row.health, PROVIDER_HEALTH_OK)
            self.assertIsNone(row.reason)
            self.assertEqual(row.consecutive_failures, 0)


if __name__ == "__main__":
    unittest.main()
