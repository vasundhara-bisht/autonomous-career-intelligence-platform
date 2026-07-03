"""Tests for OHM Phase 6 automated validation ladder."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
for entry in (str(_REPO_ROOT), str(_REPO_ROOT / "src")):
    if entry not in sys.path:
        sys.path.insert(0, entry)


class OhmValidationLadderTests(unittest.TestCase):
    def setUp(self) -> None:
        import paths

        self._env_patch = {
            "SQLITE_ENABLED": os.environ.get("SQLITE_ENABLED"),
            "AI_JOB_AGENT_DB_PATH": os.environ.get("AI_JOB_AGENT_DB_PATH"),
        }
        test_dir = paths.ensure_data_dir() / ".test_dbs"
        test_dir.mkdir(parents=True, exist_ok=True)
        self._db_path = test_dir / f"ohm_ladder_{os.getpid()}_{id(self)}.db"
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

    def test_automated_ladder_passes(self) -> None:
        from agent.ohm_validation_ladder import run_automated_validation_ladder
        from db.engine import get_session

        with get_session() as session:
            payload = run_automated_validation_ladder(session)
        self.assertTrue(payload["passed"])
        self.assertEqual(len(payload["steps"]), 4)
        self.assertTrue(all(step["passed"] for step in payload["steps"]))


if __name__ == "__main__":
    unittest.main()
