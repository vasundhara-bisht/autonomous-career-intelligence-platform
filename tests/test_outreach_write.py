"""Tests for outreach persistence service."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
for entry in (str(_REPO_ROOT), str(_SRC)):
    if entry not in sys.path:
        sys.path.insert(0, entry)


def _clear_db_caches() -> None:
    from db.engine import get_engine, get_session_factory

    get_engine.cache_clear()
    get_session_factory.cache_clear()


class OutreachWriteTests(unittest.TestCase):
    def setUp(self) -> None:
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

    def _payload(self) -> dict:
        return {
            "person_name": "Alex Lee",
            "company": "Acme",
            "outreach_channel": "linkedin",
            "hiring_signal_type": "recruiter_message",
            "status": "sent",
            "date_contacted": "2026-06-10",
            "follow_up_date": "2026-06-17",
            "notes": "Initial note",
        }

    def test_insert_and_update(self) -> None:
        from db.bootstrap import ensure_database_ready
        from db.services.outreach_write import (
            insert_outreach_attempt,
            load_outreach_attempts_ordered,
            persist_outreach_table_edits,
        )
        from db.engine import get_session

        ensure_database_ready()
        row_id = insert_outreach_attempt(self._payload())
        self.assertGreater(row_id, 0)

        count = persist_outreach_table_edits(
            [{"id": row_id, "status": "replied", "notes": "Got a reply"}]
        )
        self.assertEqual(count, 1)

        with get_session() as session:
            rows = load_outreach_attempts_ordered(session)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].status, "replied")
        self.assertEqual(rows[0].notes, "Got a reply")

    def test_insert_rejects_missing_required(self) -> None:
        from db.bootstrap import ensure_database_ready
        from db.services.outreach_write import insert_outreach_attempt

        ensure_database_ready()
        with self.assertRaises(ValueError):
            insert_outreach_attempt({"person_name": "Only Name"})
        with self.assertRaises(ValueError):
            insert_outreach_attempt(
                {
                    "person_name": "Alex",
                    "company": "Acme",
                    "outreach_channel": "linkedin",
                    "status": "sent",
                    "date_contacted": "2026-06-10",
                }
            )

    def test_insert_with_hiring_signal_url(self) -> None:
        from db.bootstrap import ensure_database_ready
        from db.engine import get_session
        from db.services.outreach_write import (
            insert_outreach_attempt,
            load_outreach_attempts_ordered,
        )

        ensure_database_ready()
        payload = self._payload()
        payload["hiring_signal_type"] = "mentor_referral"
        payload["hiring_signal_url"] = "https://example.com/signal"
        row_id = insert_outreach_attempt(payload)
        self.assertGreater(row_id, 0)

        with get_session() as session:
            rows = load_outreach_attempts_ordered(session)
        self.assertEqual(rows[0].hiring_signal_type, "mentor_referral")
        self.assertEqual(rows[0].hiring_signal_url, "https://example.com/signal")

    def test_table_edit_updates_hiring_signal(self) -> None:
        from db.bootstrap import ensure_database_ready
        from db.engine import get_session
        from db.services.outreach_write import (
            insert_outreach_attempt,
            load_outreach_attempts_ordered,
            persist_outreach_table_edits,
        )

        ensure_database_ready()
        row_id = insert_outreach_attempt(self._payload())
        count = persist_outreach_table_edits(
            [{"id": row_id, "hiring_signal_type": "personal_referral"}]
        )
        self.assertEqual(count, 1)

        with get_session() as session:
            rows = load_outreach_attempts_ordered(session)
        self.assertEqual(rows[0].hiring_signal_type, "personal_referral")

    def test_write_disabled_no_op(self) -> None:
        from db.services.outreach_write import insert_outreach_attempt

        with patch.dict(os.environ, {"SQLITE_DASHBOARD_WRITE": "0"}, clear=False):
            _clear_db_caches()
            self.assertEqual(insert_outreach_attempt(self._payload()), 0)


if __name__ == "__main__":
    unittest.main()
