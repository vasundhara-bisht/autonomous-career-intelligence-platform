"""Unit tests for LinkedIn HM overwrite cohort repair script."""

from __future__ import annotations

import json
import os
import sys
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

from sqlalchemy import select

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
_SCRIPTS = _REPO_ROOT / "scripts"
for entry in (str(_REPO_ROOT), str(_SRC), str(_SCRIPTS)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from repair_linkedin_hm_overwrite_cohort import (  # noqa: E402
    _COHORT_SQL,
    _MANIFEST_VERSION,
    _validate_cohort_rows,
    apply_job_update,
    fetch_cohort,
    load_manifest,
    run_apply_from_manifest,
    write_manifest,
)


def _clear_db_caches() -> None:
    from db.engine import get_engine, get_session_factory

    get_engine.cache_clear()
    get_session_factory.cache_clear()


class ManifestTests(unittest.TestCase):
    def _sample_doc(self) -> dict:
        return {
            "manifest_version": _MANIFEST_VERSION,
            "created_at": "2026-06-17T20:00:00Z",
            "mode": "dry-run",
            "cohort_size": 1,
            "would_update": 1,
            "excluded_invalid_recruiter_name": 0,
            "rows": [
                {
                    "job_id": 1,
                    "job_key_v2": "v2:linkedin:4417376197",
                    "title": "Senior PM",
                    "company": "Learneo",
                    "current_hiring_manager": "Not Specified",
                    "proposed_hiring_manager": "Deblina Hait",
                    "recruiter_id": 10,
                    "recruiter_key": "deblina hait",
                    "linked_at": "2026-06-01 12:00:00",
                }
            ],
        }

    def test_write_and_load_round_trip(self) -> None:
        path = Path(self._testMethodName) / "manifest.json"
        try:
            doc = self._sample_doc()
            written = write_manifest(doc, manifest_path=path)
            loaded = load_manifest(written)
            self.assertEqual(loaded["manifest_version"], _MANIFEST_VERSION)
            self.assertEqual(len(loaded["rows"]), 1)
            self.assertEqual(loaded["rows"][0]["proposed_hiring_manager"], "Deblina Hait")
        finally:
            if path.parent.exists():
                for child in path.parent.iterdir():
                    child.unlink()
                path.parent.rmdir()

    def test_load_rejects_invalid_proposed_hiring_manager(self) -> None:
        path = Path(self._testMethodName) / "bad_hm.json"
        try:
            doc = self._sample_doc()
            doc["rows"][0]["proposed_hiring_manager"] = "Not Specified"
            write_manifest(doc, manifest_path=path)
            with self.assertRaises(ValueError):
                load_manifest(path)
        finally:
            if path.parent.exists():
                for child in path.parent.iterdir():
                    child.unlink()
                path.parent.rmdir()


class ValidateCohortRowsTests(unittest.TestCase):
    def test_accepts_valid_row(self) -> None:
        rows = [
            {
                "job_id": 1,
                "job_key_v2": "v2:linkedin:1",
                "title": "PM",
                "company": "Co",
                "current_hiring_manager": "Not Specified",
                "proposed_hiring_manager": "Jane Doe",
                "recruiter_id": 2,
                "recruiter_key": "jane doe",
                "linked_at": "2026-06-01",
            }
        ]
        recoverable, excluded, _ = _validate_cohort_rows(rows)
        self.assertEqual(len(recoverable), 1)
        self.assertEqual(excluded, 0)
        self.assertEqual(recoverable[0]["proposed_hiring_manager"], "Jane Doe")

    def test_excludes_invalid_recruiter_name(self) -> None:
        rows = [
            {
                "job_id": 1,
                "job_key_v2": "v2:linkedin:1",
                "title": "PM",
                "company": "Co",
                "current_hiring_manager": "Not Specified",
                "proposed_hiring_manager": "Unknown",
                "recruiter_id": 2,
                "recruiter_key": "unknown",
                "linked_at": "2026-06-01",
            }
        ]
        recoverable, excluded, _ = _validate_cohort_rows(rows)
        self.assertEqual(len(recoverable), 0)
        self.assertEqual(excluded, 1)


class ApplyJobUpdateTests(unittest.TestCase):
    def setUp(self) -> None:
        import paths

        self._env_patch = {
            "AI_JOB_AGENT_DB_PATH": os.environ.get("AI_JOB_AGENT_DB_PATH"),
        }
        test_dir = paths.ensure_data_dir() / ".test_dbs"
        test_dir.mkdir(parents=True, exist_ok=True)
        self._db_path = test_dir / f"repair_hm_{os.getpid()}_{id(self)}.db"
        if self._db_path.exists():
            self._db_path.unlink()
        os.environ["AI_JOB_AGENT_DB_PATH"] = str(self._db_path)
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

    def _seed_overwrite_cohort_job(
        self,
        *,
        job_key_v2: str,
        hiring_manager: str | None,
        recruiter_name: str,
        extra_link: bool = False,
    ) -> tuple[int, int]:
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
            if extra_link:
                other = Recruiter(
                    recruiter_key="other recruiter",
                    recruiter_name="Other Recruiter",
                    first_seen=now,
                    last_seen=now,
                    jobs_connected=1,
                    recruiter_stage="discovered",
                    outreach_sent=False,
                    recruiter_replied=False,
                    notes="",
                    touchpoint_count=0,
                )
                session.add(other)
                session.flush()
                session.add(
                    RecruiterJobLink(
                        recruiter_id=other.id,
                        job_id=job.id,
                        linked_at=now,
                    )
                )
            session.commit()
            return int(job.id), int(recruiter.id)

    def test_repairs_sentinel_hm_from_linked_recruiter(self) -> None:
        key = "v2:li:repair-one"
        recruiter_name = "Lakshmi Das"
        _, recruiter_id = self._seed_overwrite_cohort_job(
            job_key_v2=key,
            hiring_manager="Not Specified",
            recruiter_name=recruiter_name,
        )
        from db.bootstrap import ensure_database_ready
        from db.engine import get_session
        from db.models.schema import Job

        ensure_database_ready()
        now = datetime.now(UTC).replace(tzinfo=None)
        with get_session() as session:
            applied = apply_job_update(
                session,
                job_key_v2=key,
                proposed_hiring_manager=recruiter_name,
                recruiter_id=recruiter_id,
                updated_at=now,
            )
            session.commit()
            self.assertEqual(applied, 1)
            job = session.execute(select(Job).where(Job.job_key_v2 == key)).scalar_one()
            self.assertEqual(job.hiring_manager, recruiter_name)

    def test_skips_when_hm_already_real(self) -> None:
        key = "v2:li:already-real"
        recruiter_name = "Jane Doe"
        _, recruiter_id = self._seed_overwrite_cohort_job(
            job_key_v2=key,
            hiring_manager="Jane Doe",
            recruiter_name=recruiter_name,
        )
        from db.bootstrap import ensure_database_ready
        from db.engine import get_session

        ensure_database_ready()
        now = datetime.now(UTC).replace(tzinfo=None)
        with get_session() as session:
            applied = apply_job_update(
                session,
                job_key_v2=key,
                proposed_hiring_manager=recruiter_name,
                recruiter_id=recruiter_id,
                updated_at=now,
            )
            session.commit()
            self.assertEqual(applied, 0)

    def test_skips_multi_link_job(self) -> None:
        key = "v2:li:multi-link"
        recruiter_name = "Alice Recruiter"
        _, recruiter_id = self._seed_overwrite_cohort_job(
            job_key_v2=key,
            hiring_manager="Not Specified",
            recruiter_name=recruiter_name,
            extra_link=True,
        )
        from db.bootstrap import ensure_database_ready
        from db.engine import get_session

        ensure_database_ready()
        now = datetime.now(UTC).replace(tzinfo=None)
        with get_session() as session:
            applied = apply_job_update(
                session,
                job_key_v2=key,
                proposed_hiring_manager=recruiter_name,
                recruiter_id=recruiter_id,
                updated_at=now,
            )
            session.commit()
            self.assertEqual(applied, 0)


class CohortSqlIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        import paths

        self._env_patch = {
            "AI_JOB_AGENT_DB_PATH": os.environ.get("AI_JOB_AGENT_DB_PATH"),
        }
        test_dir = paths.ensure_data_dir() / ".test_dbs"
        test_dir.mkdir(parents=True, exist_ok=True)
        self._db_path = test_dir / f"repair_cohort_{os.getpid()}_{id(self)}.db"
        if self._db_path.exists():
            self._db_path.unlink()
        os.environ["AI_JOB_AGENT_DB_PATH"] = str(self._db_path)
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

    def test_fetch_cohort_selects_single_link_sentinel_hm(self) -> None:
        from db.bootstrap import ensure_database_ready
        from db.engine import get_session
        from db.models.schema import Job, Recruiter, RecruiterJobLink
        from db.services.recruiter_enrichment import generate_recruiter_key

        ensure_database_ready()
        now = datetime.now(UTC).replace(tzinfo=None)
        with get_session() as session:
            job = Job(
                job_key="pm::co",
                job_key_v2="v2:li:cohort-in",
                title="PM",
                company="Co",
                source="linkedin",
                hiring_manager="Not Specified",
                created_at=now,
                updated_at=now,
            )
            session.add(job)
            session.flush()
            recruiter = Recruiter(
                recruiter_key=generate_recruiter_key("Bob Two"),
                recruiter_name="Bob Two",
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

        with get_session() as session:
            cohort = fetch_cohort(session)
            self.assertEqual(len(cohort), 1)
            self.assertEqual(cohort[0]["job_key_v2"], "v2:li:cohort-in")
            self.assertEqual(cohort[0]["proposed_hiring_manager"], "Bob Two")


class ApplyFromManifestTests(unittest.TestCase):
    def test_apply_from_manifest_updates_rows(self) -> None:
        manifest_dir = Path(self._testMethodName)
        manifest_path = manifest_dir / "repair.json"
        manifest_dir.mkdir(exist_ok=True)
        doc = {
            "manifest_version": _MANIFEST_VERSION,
            "created_at": "2026-06-17T20:00:00Z",
            "mode": "dry-run",
            "cohort_size": 1,
            "would_update": 1,
            "rows": [
                {
                    "job_id": 1,
                    "job_key_v2": "v2:linkedin:1",
                    "title": "PM",
                    "company": "A",
                    "current_hiring_manager": "Not Specified",
                    "proposed_hiring_manager": "Alice One",
                    "recruiter_id": 10,
                    "recruiter_key": "alice one",
                    "linked_at": "2026-06-01",
                }
            ],
        }
        write_manifest(doc, manifest_path=manifest_path)

        session = MagicMock()
        session_cm = MagicMock()
        session_cm.__enter__.return_value = session
        session_cm.__exit__.return_value = False

        with (
            patch("repair_linkedin_hm_overwrite_cohort.ensure_database_ready"),
            patch("repair_linkedin_hm_overwrite_cohort.get_session", return_value=session_cm),
            patch("repair_linkedin_hm_overwrite_cohort._sql_validation", return_value={"x": 1}),
            patch("repair_linkedin_hm_overwrite_cohort.apply_job_update", return_value=1) as mock_apply,
        ):
            rc = run_apply_from_manifest(manifest_path=manifest_path, limit=1)

        self.assertEqual(rc, 0)
        self.assertEqual(mock_apply.call_count, 1)
        session.commit.assert_called_once()

        if manifest_dir.exists():
            for child in manifest_dir.iterdir():
                child.unlink()
            manifest_dir.rmdir()


class CohortSqlTests(unittest.TestCase):
    def test_cohort_filters_linkedin_sentinel_hm_single_link(self) -> None:
        lowered = _COHORT_SQL.lower()
        self.assertIn("source = 'linkedin'", lowered)
        self.assertIn("not specified", lowered)
        self.assertIn("recruiter_job_links", lowered)
        self.assertIn("having count(*) = 1", lowered)
        self.assertIn("none", lowered)


if __name__ == "__main__":
    unittest.main()
