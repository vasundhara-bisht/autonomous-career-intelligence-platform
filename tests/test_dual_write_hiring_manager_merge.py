"""Tests for hiring_manager sentinel merge in dual-write jobs upsert."""

from __future__ import annotations

import os
import sys
import unittest
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
for entry in (str(_REPO_ROOT), str(_SRC)):
    if entry not in sys.path:
        sys.path.insert(0, entry)


def _clear_db_caches() -> None:
    from db.engine import get_engine, get_session_factory

    get_engine.cache_clear()
    get_session_factory.cache_clear()


class HiringManagerSentinelTests(unittest.TestCase):
    def test_sentinel_variants(self) -> None:
        from db.services.recruiter_enrichment import is_hiring_manager_sentinel

        for value in (None, "", "   ", "Not Specified", "UNKNOWN", "nan", "NONE"):
            with self.subTest(value=value):
                self.assertTrue(is_hiring_manager_sentinel(value))

    def test_real_name_not_sentinel(self) -> None:
        from db.services.recruiter_enrichment import is_hiring_manager_sentinel

        self.assertFalse(is_hiring_manager_sentinel("Jane Doe"))


class DualWriteHiringManagerMergeTests(unittest.TestCase):
    def setUp(self) -> None:
        import paths

        self._env_patch = {
            "SQLITE_ENABLED": os.environ.get("SQLITE_ENABLED"),
            "SQLITE_DUAL_WRITE": os.environ.get("SQLITE_DUAL_WRITE"),
            "AI_JOB_AGENT_DB_PATH": os.environ.get("AI_JOB_AGENT_DB_PATH"),
        }
        test_dir = paths.ensure_data_dir() / ".test_dbs"
        test_dir.mkdir(parents=True, exist_ok=True)
        self._db_path = test_dir / f"dual_write_hm_{os.getpid()}_{id(self)}.db"
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

    def _seed_job(
        self,
        *,
        job_key_v2: str,
        hiring_manager: str | None,
        source: str = "linkedin",
    ) -> int:
        from db.bootstrap import ensure_database_ready
        from db.engine import get_session
        from db.models.schema import Job

        ensure_database_ready()
        now = datetime.now(UTC).replace(tzinfo=None)
        with get_session() as session:
            job = Job(
                job_key="pm::co",
                job_key_v2=job_key_v2,
                title="PM",
                company="Co",
                source=source,
                hiring_manager=hiring_manager,
                created_at=now,
                updated_at=now,
            )
            session.add(job)
            session.commit()
            session.refresh(job)
            return int(job.id)

    def _seed_job_with_recruiter_link(
        self,
        *,
        job_key_v2: str,
        hiring_manager: str,
        recruiter_name: str,
    ) -> int:
        from db.bootstrap import ensure_database_ready
        from db.engine import get_session
        from db.models.schema import Job, Recruiter, RecruiterJobLink
        from db.services.recruiter_enrichment import generate_recruiter_key

        ensure_database_ready()
        now = datetime.now(UTC).replace(tzinfo=None)
        with get_session() as session:
            job = Job(
                job_key="pm::co",
                job_key_v2=job_key_v2,
                title="PM",
                company="Co",
                source="linkedin",
                hiring_manager=hiring_manager,
                created_at=now,
                updated_at=now,
            )
            session.add(job)
            session.flush()
            recruiter = Recruiter(
                recruiter_key=generate_recruiter_key(recruiter_name),
                recruiter_name=recruiter_name,
                first_seen=now,
                last_seen=now,
                jobs_connected=1,
                recruiter_stage="discovered",
                outreach_sent=False,
                recruiter_replied=False,
                notes="",
                touchpoint_count=0,
            )
            session.add(recruiter)
            session.flush()
            session.add(
                RecruiterJobLink(
                    recruiter_id=recruiter.id,
                    job_id=job.id,
                    linked_at=now,
                )
            )
            session.commit()
            return int(job.id)

    def _upsert_hiring_manager(
        self,
        job_key_v2: str,
        *,
        hiring_manager: str | None = "Not Specified",
    ) -> None:
        from db.bootstrap import ensure_database_ready
        from db.engine import get_session
        from db.services.dual_write import _upsert_jobs

        ensure_database_ready()
        payload: dict = {
            "JOB_KEY_V2": job_key_v2,
            "title": "PM",
            "company": "Co",
            "source": "linkedin",
        }
        if hiring_manager is not None:
            payload["hiring_manager"] = hiring_manager
        with get_session() as session:
            _upsert_jobs(session, jobs=[payload])
            session.commit()

    def _load_hiring_manager(self, job_key_v2: str) -> str | None:
        from db.engine import get_session
        from db.models.schema import Job

        with get_session() as session:
            job = session.execute(
                select(Job).where(Job.job_key_v2 == job_key_v2)
            ).scalar_one()
            return job.hiring_manager

    def test_preserve_real_on_incoming_not_specified(self) -> None:
        key = "v2:li:preserve-real"
        self._seed_job(job_key_v2=key, hiring_manager="Jane Doe")
        self._upsert_hiring_manager(key, hiring_manager="Not Specified")
        self.assertEqual(self._load_hiring_manager(key), "Jane Doe")

    def test_preserve_real_on_incoming_null(self) -> None:
        key = "v2:li:preserve-null"
        self._seed_job(job_key_v2=key, hiring_manager="Jane Doe")
        self._upsert_hiring_manager(key, hiring_manager=None)
        self.assertEqual(self._load_hiring_manager(key), "Jane Doe")

    def test_upgrade_sentinel_on_incoming_real(self) -> None:
        key = "v2:li:upgrade-sentinel"
        self._seed_job(job_key_v2=key, hiring_manager="Not Specified")
        self._upsert_hiring_manager(key, hiring_manager="Jane Doe")
        self.assertEqual(self._load_hiring_manager(key), "Jane Doe")

    def test_update_real_on_incoming_real(self) -> None:
        key = "v2:li:update-real"
        self._seed_job(job_key_v2=key, hiring_manager="Alice")
        self._upsert_hiring_manager(key, hiring_manager="Bob")
        self.assertEqual(self._load_hiring_manager(key), "Bob")

    def test_sentinel_on_sentinel_no_change(self) -> None:
        key = "v2:li:sentinel-stable"
        self._seed_job(job_key_v2=key, hiring_manager="Not Specified")
        self._upsert_hiring_manager(key, hiring_manager="Unknown")
        self.assertEqual(self._load_hiring_manager(key), "Not Specified")

    def test_insert_new_job_sentinel(self) -> None:
        key = "v2:li:insert-sentinel"
        self._upsert_hiring_manager(key, hiring_manager="Not Specified")
        self.assertEqual(self._load_hiring_manager(key), "Not Specified")

    def test_insert_new_job_real(self) -> None:
        key = "v2:li:insert-real"
        self._upsert_hiring_manager(key, hiring_manager="Jane Doe")
        self.assertEqual(self._load_hiring_manager(key), "Jane Doe")

    def test_cohort_shape_preserves_repaired_hm_with_link_on_sentinel_scrape(self) -> None:
        """Simulate 33-cohort repair: real HM + recruiter link survives sentinel scrape."""
        key = "v2:li:cohort-overwrite-regression"
        recruiter_name = "Lakshmi Das"
        self._seed_job_with_recruiter_link(
            job_key_v2=key,
            hiring_manager=recruiter_name,
            recruiter_name=recruiter_name,
        )
        self._upsert_hiring_manager(key, hiring_manager="Not Specified")
        self.assertEqual(self._load_hiring_manager(key), recruiter_name)


if __name__ == "__main__":
    unittest.main()
