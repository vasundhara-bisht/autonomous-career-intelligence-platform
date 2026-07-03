"""Alembic migration tests for outreach_attempts."""

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
    from db.bootstrap import _reset_bootstrap_guard
    from db.engine import get_engine, get_session_factory

    _reset_bootstrap_guard()
    get_engine.cache_clear()
    get_session_factory.cache_clear()


class OutreachMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._data = Path(self._tmpdir.name)
        self._env_patch = patch.dict(
            os.environ,
            {
                "AI_JOB_AGENT_DATA_DIR": str(self._data),
                "AI_JOB_AGENT_DB_PATH": str(self._data / "test.db"),
            },
            clear=False,
        )
        self._env_patch.start()
        _clear_db_caches()

    def tearDown(self) -> None:
        self._env_patch.stop()
        _clear_db_caches()
        self._tmpdir.cleanup()

    def test_upgrade_creates_outreach_attempts_table(self) -> None:
        from sqlalchemy import inspect

        from db.bootstrap import ensure_database_ready, upgrade_schema
        from db.engine import get_engine

        upgrade_schema(revision="head")
        ensure_database_ready()
        inspector = inspect(get_engine())
        self.assertIn("outreach_attempts", inspector.get_table_names())
        columns = {col["name"] for col in inspector.get_columns("outreach_attempts")}
        self.assertIn("hiring_signal_type", columns)
        self.assertIn("hiring_signal_url", columns)


if __name__ == "__main__":
    unittest.main()
