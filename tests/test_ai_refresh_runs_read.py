"""Tests for AI refresh run read layer."""

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


class AiRefreshRunsReadTests(unittest.TestCase):
    def setUp(self) -> None:
        import paths

        self._env_patch = {
            "SQLITE_ENABLED": os.environ.get("SQLITE_ENABLED"),
            "AI_JOB_AGENT_DB_PATH": os.environ.get("AI_JOB_AGENT_DB_PATH"),
        }
        test_dir = paths.ensure_data_dir() / ".test_dbs"
        test_dir.mkdir(parents=True, exist_ok=True)
        self._db_path = test_dir / f"ai_refresh_read_{os.getpid()}_{id(self)}.db"
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

    def test_load_latest_and_history(self) -> None:
        from db.bootstrap import ensure_database_ready
        from db.engine import get_session
        from db.models.schema import AiRefreshRun
        from db.read.ai_refresh_runs import (
            load_ai_refresh_run_history,
            load_latest_ai_refresh_run_info,
        )

        ensure_database_ready()
        now = datetime.now(UTC).replace(tzinfo=None)
        with get_session() as session:
            session.add(
                AiRefreshRun(
                    started_at=now,
                    completed_at=now,
                    status="completed",
                    preset="backlog",
                    cohort_size=10,
                    eligible_count=8,
                    scored_count=5,
                    skipped_by_cap_count=3,
                )
            )
            session.commit()

        with get_session() as session:
            latest = load_latest_ai_refresh_run_info(session)
            self.assertIsNotNone(latest)
            assert latest is not None
            self.assertEqual(latest["preset"], "backlog")
            self.assertEqual(int(latest["scored_count"]), 5)
            history = load_ai_refresh_run_history(session, limit=10)
            self.assertEqual(len(history), 1)


if __name__ == "__main__":
    unittest.main()
