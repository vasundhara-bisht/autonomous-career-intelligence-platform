"""Tests for D4 SQLite pipeline read switch."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import UTC, datetime
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


class PipelineReadFlagTests(unittest.TestCase):
    def test_pipeline_read_default_on_without_env(self) -> None:
        from db.read.engine import pipeline_read_enabled

        keys = ("SQLITE_ENABLED", "SQLITE_PIPELINE_READ")
        saved = {k: os.environ.pop(k, None) for k in keys}
        try:
            self.assertTrue(pipeline_read_enabled())
        finally:
            for k, v in saved.items():
                if v is not None:
                    os.environ[k] = v

    def test_pipeline_read_requires_sqlite_enabled(self) -> None:
        from db.read.engine import pipeline_read_enabled

        with patch.dict(os.environ, {"SQLITE_ENABLED": "0", "SQLITE_PIPELINE_READ": "1"}, clear=False):
            from importlib import reload

            import db.config as cfg

            reload(cfg)
            import db.read.engine as eng

            reload(eng)
            self.assertFalse(eng.pipeline_read_enabled())


class HistoricalIndexDbTests(unittest.TestCase):
    def setUp(self) -> None:
        import paths

        self._tmpdir = tempfile.TemporaryDirectory()
        self._data = Path(self._tmpdir.name)
        self._env_patch = patch.dict(
            os.environ,
            {
                "AI_JOB_AGENT_DATA_DIR": str(self._data),
                "AI_JOB_AGENT_DB_PATH": str(self._data / "test.db"),
                "SQLITE_ENABLED": "1",
                "SQLITE_PIPELINE_READ": "1",
            },
            clear=False,
        )
        self._env_patch.start()
        _clear_db_caches()

    def tearDown(self) -> None:
        self._env_patch.stop()
        _clear_db_caches()
        self._tmpdir.cleanup()

    def test_db_historical_index_matches_csv_shape(self) -> None:
        from db.bootstrap import ensure_database_ready
        from db.engine import get_session
        from db.models.schema import AiEvaluation, Job, UserJobState
        from db.read.historical_index import load_historical_index_from_db
        from agent.historical_persistence import (
            _load_historical_index_from_csv,
            load_historical_index,
            lookup_historical_row,
        )
        import paths
        import pandas as pd

        ensure_database_ready()
        v2 = "v2:greenhouse:acme:role123"
        legacy = "product manager::acme"
        with get_session() as session:
            job = Job(
                job_key=legacy,
                job_key_v2=v2,
                title="Product Manager",
                company="Acme",
                source="greenhouse",
            )
            session.add(job)
            session.flush()
            session.add(
                AiEvaluation(
                    job_id=job.id,
                    ai_status="scored",
                    ai_score=7.0,
                    reason="Good fit",
                    evaluated_at=datetime.now(UTC).replace(tzinfo=None),
                )
            )
            session.add(
                UserJobState(
                    job_id=job.id,
                    applied=False,
                    rejected=False,
                )
            )
            session.commit()

        hist_path = paths.historical_jobs_csv()
        hist_path.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(
            [
                {
                    "JOB_KEY": legacy,
                    "JOB_KEY_V2": v2,
                    "title": "Product Manager",
                    "company": "Acme",
                    "source": "greenhouse",
                    "link": "",
                    "ai_score": 7.0,
                    "ai_status": "scored",
                    "reason": "Good fit",
                    "hiring_manager": "",
                    "first_seen": "",
                    "last_seen": "",
                    "times_seen": 1,
                    "currently_active": True,
                    "applied": False,
                    "rejected": False,
                    "interview": False,
                    "offer": False,
                    "notes": "",
                    "posted_at_date": "",
                    "age_days": "",
                }
            ]
        ).to_csv(hist_path, index=False)

        db_index = load_historical_index_from_db()
        csv_index = _load_historical_index_from_csv()
        self.assertIn(v2, db_index["by_v2"])
        self.assertIn(v2, csv_index["by_v2"])

        job = {"JOB_KEY_V2": v2, "JOB_KEY": legacy, "title": "Product Manager", "company": "Acme"}
        db_row = lookup_historical_row(db_index, job)
        csv_row = lookup_historical_row(csv_index, job)
        self.assertIsNotNone(db_row)
        self.assertIsNotNone(csv_row)
        self.assertEqual(str(db_row.get("ai_status")).lower(), "scored")
        self.assertEqual(str(csv_row.get("ai_status")).lower(), "scored")

        index = load_historical_index()
        self.assertEqual(getattr(load_historical_index, "_last_source", None), "sqlite")


class DescriptionStoreDbTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._data = Path(self._tmpdir.name)
        self._env_patch = patch.dict(
            os.environ,
            {
                "AI_JOB_AGENT_DATA_DIR": str(self._data),
                "AI_JOB_AGENT_DB_PATH": str(self._data / "test.db"),
                "SQLITE_ENABLED": "1",
                "SQLITE_PIPELINE_READ": "1",
            },
            clear=False,
        )
        self._env_patch.start()
        _clear_db_caches()

    def tearDown(self) -> None:
        self._env_patch.stop()
        _clear_db_caches()
        self._tmpdir.cleanup()

    def test_db_description_store_hydrates_job(self) -> None:
        from db.bootstrap import ensure_database_ready
        from db.engine import get_session
        from db.models.schema import Job, JobDescription
        from agent.job_description_persistence import (
            load_description_store,
            try_hydrate_from_store,
        )

        ensure_database_ready()
        v2 = "v2:greenhouse:acme:role456"
        desc_text = "A" * 250
        with get_session() as session:
            job = Job(
                job_key="pm::acme",
                job_key_v2=v2,
                title="PM",
                company="Acme",
            )
            session.add(job)
            session.flush()
            session.add(
                JobDescription(
                    job_id=job.id,
                    job_key_v2=v2,
                    description=desc_text,
                    source="greenhouse",
                    last_updated=datetime.now(UTC).replace(tzinfo=None),
                )
            )
            session.commit()

        store = load_description_store()
        job = {"JOB_KEY_V2": v2, "JOB_KEY": "pm::acme"}
        stats: dict = {}
        try_hydrate_from_store(job, store, stats, bucket="needs_ai_only")
        self.assertEqual(job.get("description"), desc_text)
        self.assertEqual(stats.get("reused"), 1)


class QueryStateDbTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._data = Path(self._tmpdir.name)
        self._env_patch = patch.dict(
            os.environ,
            {
                "AI_JOB_AGENT_DATA_DIR": str(self._data),
                "AI_JOB_AGENT_DB_PATH": str(self._data / "test.db"),
                "SQLITE_ENABLED": "1",
                "SQLITE_QUERY_STATE_READ": "1",
            },
            clear=False,
        )
        self._env_patch.start()
        _clear_db_caches()

    def tearDown(self) -> None:
        self._env_patch.stop()
        _clear_db_caches()
        self._tmpdir.cleanup()

    def test_load_state_from_db(self) -> None:
        from db.bootstrap import ensure_database_ready
        from db.engine import get_session
        from db.models.schema import QueryCooldownState
        from scraper.linkedin_query_orchestrator import _load_state

        ensure_database_ready()
        with get_session() as session:
            session.add(
                QueryCooldownState(
                    query_id="top_applicants_anchor",
                    last_run_at=1710000000.0,
                    domain_rotation_index=2,
                )
            )
            session.commit()

        state = _load_state()
        self.assertEqual(state["domain_rotation_index"], 2)
        self.assertAlmostEqual(
            state["last_run_by_query_id"]["top_applicants_anchor"], 1710000000.0
        )


class RoutingParityFixtureTests(unittest.TestCase):
    def test_routing_split_unchanged_for_same_index(self) -> None:
        from agent.historical_persistence import lookup_historical_row
        from agent.main import _historical_job_needs_ai_fallback, materialize_fully_processed_job

        v2_scored = "v2:linkedin:co:123"
        index = {
            "by_v2": {
                v2_scored: {
                    "JOB_KEY_V2": v2_scored,
                    "JOB_KEY": "pm::co",
                    "ai_status": "scored",
                    "ai_score": 8.0,
                    "reason": "Strong",
                }
            },
            "by_legacy": {},
        }
        intake = [
            {"JOB_KEY_V2": v2_scored, "title": "PM", "company": "Co"},
            {"JOB_KEY_V2": "v2:greenhouse:new:999", "title": "New", "company": "X"},
        ]
        fully_processed = []
        brand_new = []
        for job in intake:
            row = lookup_historical_row(index, job)
            if not row:
                brand_new.append(job)
            elif _historical_job_needs_ai_fallback(row):
                brand_new.append(job)
            else:
                materialize_fully_processed_job(job, row)
                fully_processed.append(job)

        self.assertEqual(len(fully_processed), 1)
        self.assertEqual(len(brand_new), 1)
        self.assertEqual(fully_processed[0].get("ai_status"), "scored")


if __name__ == "__main__":
    unittest.main()
