"""Tests for process-level ensure_database_ready bootstrap guard."""

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


class BootstrapGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._data = Path(self._tmpdir.name)
        os.environ["AI_JOB_AGENT_DATA_DIR"] = str(self._data)
        os.environ["AI_JOB_AGENT_DB_PATH"] = str(self._data / "test.db")
        os.environ["SQLITE_ENABLED"] = "1"
        _clear_db_caches()
        from db.bootstrap import _reset_bootstrap_guard

        _reset_bootstrap_guard()

    def tearDown(self) -> None:
        from db.bootstrap import _reset_bootstrap_guard

        _reset_bootstrap_guard()
        _clear_db_caches()
        self._tmpdir.cleanup()
        for key in ("AI_JOB_AGENT_DATA_DIR", "AI_JOB_AGENT_DB_PATH", "SQLITE_ENABLED"):
            os.environ.pop(key, None)

    def test_repeated_calls_skip_alembic_upgrade(self) -> None:
        from db.bootstrap import ensure_database_ready

        with patch("db.bootstrap.command.upgrade") as mock_upgrade:
            ensure_database_ready()
            ensure_database_ready()
            ensure_database_ready()
            mock_upgrade.assert_called_once()

    def test_different_db_paths_each_run_upgrade_once(self) -> None:
        from db.bootstrap import ensure_database_ready

        db_path_b = self._data / "other.db"
        with patch("db.bootstrap.command.upgrade") as mock_upgrade:
            ensure_database_ready()
            os.environ["AI_JOB_AGENT_DB_PATH"] = str(db_path_b)
            _clear_db_caches()
            ensure_database_ready()
            self.assertEqual(mock_upgrade.call_count, 2)

    def test_fresh_database_still_migrates(self) -> None:
        from db.bootstrap import ensure_database_ready
        from db.engine import get_engine
        from sqlalchemy import inspect

        db_path = ensure_database_ready()
        self.assertTrue(db_path.is_file())
        inspector = inspect(get_engine())
        tables = set(inspector.get_table_names())
        self.assertIn("jobs", tables)
        self.assertIn("alembic_version", tables)
