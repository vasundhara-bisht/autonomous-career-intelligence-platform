"""Tests for Hiring Manager recruiter enrichment service."""

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


class RecruiterEnrichmentTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._data = Path(self._tmpdir.name)
        self._env_patch = patch.dict(
            os.environ,
            {
                "AI_JOB_AGENT_DATA_DIR": str(self._data),
                "AI_JOB_AGENT_DB_PATH": str(self._data / "test.db"),
                "SQLITE_ENABLED": "1",
            },
            clear=False,
        )
        self._env_patch.start()
        _clear_db_caches()

    def tearDown(self) -> None:
        self._env_patch.stop()
        _clear_db_caches()
        self._tmpdir.cleanup()

    def _seed_job(self, *, v2: str = "v2:test:co:1", hiring_manager: str = "Not Specified"):
        from db.bootstrap import ensure_database_ready
        from db.engine import get_session
        from db.models.schema import Job, UserJobState

        ensure_database_ready()
        now = datetime.now(UTC).replace(tzinfo=None)
        with get_session() as session:
            job = Job(
                job_key="pm::co",
                job_key_v2=v2,
                title="PM",
                company="Co",
                source="instahyre",
                hiring_manager=hiring_manager,
            )
            session.add(job)
            session.flush()
            session.add(
                UserJobState(
                    job_id=job.id,
                    applied=False,
                    rejected=False,
                    pipeline_stage="New",
                    updated_at=now,
                )
            )
            session.commit()
            return int(job.id)

    def test_valid_hm_creates_recruiter_link_and_updates_job(self) -> None:
        from db.engine import get_session
        from db.models.schema import Job, Recruiter, RecruiterJobLink
        from db.services.recruiter_enrichment import sync_recruiter_from_hiring_manager

        job_id = self._seed_job()
        with get_session() as session:
            result = sync_recruiter_from_hiring_manager(
                session,
                job_id=job_id,
                hiring_manager="Priya Sharma",
                company="Co",
                job_source="instahyre",
            )
            session.commit()

        self.assertEqual(result.outcome, "linked")
        self.assertTrue(result.recruiter_created)
        self.assertTrue(result.link_added)

        with get_session() as session:
            job = session.get(Job, job_id)
            assert job is not None
            self.assertEqual(job.hiring_manager, "Priya Sharma")
            recruiters = session.query(Recruiter).all()
            self.assertEqual(len(recruiters), 1)
            links = session.query(RecruiterJobLink).filter_by(job_id=job_id).all()
            self.assertEqual(len(links), 1)

    def test_existing_recruiter_updates_last_seen_no_duplicate_row(self) -> None:
        from db.engine import get_session
        from db.models.schema import Recruiter
        from db.services.recruiter_enrichment import sync_recruiter_from_hiring_manager

        job_id = self._seed_job()
        with get_session() as session:
            sync_recruiter_from_hiring_manager(
                session,
                job_id=job_id,
                hiring_manager="Priya Sharma",
                company="Co",
            )
            session.commit()

        with get_session() as session:
            result = sync_recruiter_from_hiring_manager(
                session,
                job_id=job_id,
                hiring_manager="Priya Sharma",
                company="Co",
            )
            session.commit()

        self.assertEqual(result.outcome, "updated_display")
        self.assertFalse(result.link_added)
        with get_session() as session:
            self.assertEqual(session.query(Recruiter).count(), 1)

    def test_hm_change_a_to_b_preserves_both_links(self) -> None:
        from db.engine import get_session
        from db.models.schema import Recruiter, RecruiterJobLink
        from db.services.recruiter_enrichment import sync_recruiter_from_hiring_manager

        job_id = self._seed_job()
        with get_session() as session:
            sync_recruiter_from_hiring_manager(
                session, job_id=job_id, hiring_manager="Alice Recruiter", company="Co"
            )
            session.commit()
        with get_session() as session:
            sync_recruiter_from_hiring_manager(
                session, job_id=job_id, hiring_manager="Bob Recruiter", company="Co"
            )
            session.commit()

        with get_session() as session:
            from db.models.schema import Job

            job = session.get(Job, job_id)
            assert job is not None
            self.assertEqual(job.hiring_manager, "Bob Recruiter")
            self.assertEqual(
                session.query(RecruiterJobLink).filter_by(job_id=job_id).count(), 2
            )
            self.assertEqual(session.query(Recruiter).count(), 2)

    def test_cleared_to_not_specified_preserves_links(self) -> None:
        from db.engine import get_session
        from db.models.schema import Job, RecruiterJobLink
        from db.services.recruiter_enrichment import (
            NOT_SPECIFIED_HIRING_MANAGER,
            sync_recruiter_from_hiring_manager,
        )

        job_id = self._seed_job()
        with get_session() as session:
            sync_recruiter_from_hiring_manager(
                session, job_id=job_id, hiring_manager="Alice Recruiter"
            )
            session.commit()
        with get_session() as session:
            result = sync_recruiter_from_hiring_manager(
                session, job_id=job_id, hiring_manager=""
            )
            session.commit()

        self.assertEqual(result.outcome, "cleared_display")
        with get_session() as session:
            job = session.get(Job, job_id)
            assert job is not None
            self.assertEqual(job.hiring_manager, NOT_SPECIFIED_HIRING_MANAGER)
            self.assertEqual(
                session.query(RecruiterJobLink).filter_by(job_id=job_id).count(), 1
            )

    def test_invalid_name_skips_recruiter_creation(self) -> None:
        from db.engine import get_session
        from db.models.schema import Job, Recruiter, RecruiterJobLink
        from db.services.recruiter_enrichment import (
            NOT_SPECIFIED_HIRING_MANAGER,
            sync_recruiter_from_hiring_manager,
        )

        job_id = self._seed_job()
        with get_session() as session:
            result = sync_recruiter_from_hiring_manager(
                session, job_id=job_id, hiring_manager="unknown"
            )
            session.commit()

        self.assertEqual(result.outcome, "cleared_display")
        with get_session() as session:
            self.assertEqual(session.query(Recruiter).count(), 0)
            self.assertEqual(session.query(RecruiterJobLink).count(), 0)
            job = session.get(Job, job_id)
            assert job is not None
            self.assertEqual(job.hiring_manager, NOT_SPECIFIED_HIRING_MANAGER)

    def test_jobs_connected_in_view_after_append(self) -> None:
        from db.bootstrap import ensure_database_ready
        from db.engine import get_session
        from db.read.crm import load_active_recruiters_view_df
        from db.services.recruiter_enrichment import sync_recruiter_from_hiring_manager

        job_id = self._seed_job()
        with get_session() as session:
            sync_recruiter_from_hiring_manager(
                session, job_id=job_id, hiring_manager="Priya Sharma", company="Co"
            )
            session.commit()

        ensure_database_ready()
        with get_session() as session:
            df = load_active_recruiters_view_df(session)
        row = df[df["RECRUITER_KEY"] == "priya sharma"].iloc[0]
        self.assertEqual(int(row["jobs_connected"]), 1)


if __name__ == "__main__":
    unittest.main()
