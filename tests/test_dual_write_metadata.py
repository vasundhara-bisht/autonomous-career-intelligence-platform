"""Tests for D2.1 query/feed metadata dual-write and view linkage."""

from __future__ import annotations

import os
import sys
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import select, text

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
for entry in (str(_REPO_ROOT), str(_SRC)):
    if entry not in sys.path:
        sys.path.insert(0, entry)


def _clear_db_caches() -> None:
    from db.engine import get_engine, get_session_factory

    get_engine.cache_clear()
    get_session_factory.cache_clear()


class DualWriteMetadataTests(unittest.TestCase):
    def setUp(self) -> None:
        import paths

        self._env_patch = {
            "SQLITE_ENABLED": os.environ.get("SQLITE_ENABLED"),
            "SQLITE_DUAL_WRITE": os.environ.get("SQLITE_DUAL_WRITE"),
            "AI_JOB_AGENT_DB_PATH": os.environ.get("AI_JOB_AGENT_DB_PATH"),
        }
        test_dir = paths.ensure_data_dir() / ".test_dbs"
        test_dir.mkdir(parents=True, exist_ok=True)
        self._db_path = test_dir / f"dual_write_meta_{os.getpid()}_{id(self)}.db"
        if self._db_path.exists():
            self._db_path.unlink()
        os.environ["AI_JOB_AGENT_DB_PATH"] = str(self._db_path)
        os.environ["SQLITE_ENABLED"] = "1"
        os.environ["SQLITE_DUAL_WRITE"] = "1"
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

    def test_dual_write_links_query_run_and_view_metadata(self) -> None:
        from db.bootstrap import ensure_database_ready
        from db.engine import get_session
        from db.models.schema import JobObservation
        from db.services.dual_write import dual_write_runtime_snapshot

        ensure_database_ready()
        jobs = [
            {
                "JOB_KEY_V2": "v2:li:1",
                "JOB_KEY": "pm::acme",
                "title": "PM",
                "company": "Acme",
                "location": "Bangalore",
                "link": "https://example.com/1",
                "source": "linkedin",
                "time_posted": "1d",
                "ai_status": "scored",
                "ai_score": 8.0,
                "linkedin_query_id": "q1",
                "linkedin_query_group": "g1",
                "linkedin_query_label": "label1",
                "linkedin_filter_profile": "fp1",
                "linkedin_query_role": "anchor",
                "linkedin_run_ts": "2026-01-01T00:00:00+00:00",
            },
            {
                "JOB_KEY_V2": "v2:ih:1",
                "JOB_KEY": "pm::beta",
                "title": "PM2",
                "company": "Beta",
                "location": "Mumbai",
                "link": "https://example.com/2",
                "source": "instahyre",
                "time_posted": "2d",
                "ai_status": "scored",
                "ai_score": 7.0,
                "instahyre_feed_id": "feed1",
                "instahyre_query_id": "feed1",
                "instahyre_query_label": "pm feed",
                "instahyre_run_ts": "2026-01-02T00:00:00+00:00",
            },
        ]
        report = dual_write_runtime_snapshot(jobs=jobs, persistence_cohort_count=2)
        self.assertTrue(report["success"], msg=report.get("error"))

        with get_session() as session:
            obs_rows = session.execute(select(JobObservation)).scalars().all()
            self.assertEqual(len(obs_rows), 2)
            self.assertTrue(all(o.query_run_id is not None for o in obs_rows))

            view = session.execute(
                text(
                    """
                    SELECT JOB_KEY_V2, linkedin_query_id, instahyre_feed_id
                    FROM current_jobs_view
                    ORDER BY JOB_KEY_V2
                    """
                )
            ).mappings().all()
            self.assertEqual(len(view), 2)
            by_key = {row["JOB_KEY_V2"]: row for row in view}
            self.assertEqual(by_key["v2:ih:1"]["instahyre_feed_id"], "feed1")
            self.assertEqual(by_key["v2:li:1"]["linkedin_query_id"], "q1")


if __name__ == "__main__":
    unittest.main()
