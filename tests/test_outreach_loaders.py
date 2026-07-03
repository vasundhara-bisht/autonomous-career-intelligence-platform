"""Tests for outreach dashboard loaders."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
for entry in (str(_REPO_ROOT), str(_REPO_ROOT / "dashboard"), str(_SRC)):
    if entry not in sys.path:
        sys.path.insert(0, entry)


def _clear_db_caches() -> None:
    from db.engine import get_engine, get_session_factory

    get_engine.cache_clear()
    get_session_factory.cache_clear()


class OutreachLoaderTests(unittest.TestCase):
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

    def test_round_trip_load(self) -> None:
        from db.bootstrap import ensure_database_ready
        from db.services.outreach_write import insert_outreach_attempt
        from loaders import load_outreach_df, normalize_outreach_columns

        ensure_database_ready()
        insert_outreach_attempt(
            {
                "person_name": "Sam",
                "company": "Beta",
                "outreach_channel": "email",
                "hiring_signal_type": "direct_outreach",
                "status": "planned",
                "date_contacted": "2026-06-01",
                "hiring_signal_url": "https://example.com/post",
            }
        )
        df = load_outreach_df()
        self.assertEqual(len(df), 1)
        self.assertEqual(df.iloc[0]["person_name"], "Sam")
        self.assertEqual(df.iloc[0]["hiring_signal_type"], "direct_outreach")
        self.assertEqual(df.iloc[0]["hiring_signal_url"], "https://example.com/post")
        normalized = normalize_outreach_columns(df)
        self.assertIn("status", normalized.columns)


if __name__ == "__main__":
    unittest.main()
