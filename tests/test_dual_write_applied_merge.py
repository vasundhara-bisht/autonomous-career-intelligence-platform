"""Tests for applied-status merge in dual-write user_job_state upsert."""

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


class DualWriteAppliedMergeTests(unittest.TestCase):
    def setUp(self) -> None:
        import paths

        self._env_patch = {
            "SQLITE_ENABLED": os.environ.get("SQLITE_ENABLED"),
            "SQLITE_DUAL_WRITE": os.environ.get("SQLITE_DUAL_WRITE"),
            "AI_JOB_AGENT_DB_PATH": os.environ.get("AI_JOB_AGENT_DB_PATH"),
        }
        test_dir = paths.ensure_data_dir() / ".test_dbs"
        test_dir.mkdir(parents=True, exist_ok=True)
        self._db_path = test_dir / f"dual_write_applied_{os.getpid()}_{id(self)}.db"
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

    def _seed_job_with_state(
        self,
        *,
        job_key_v2: str,
        pipeline_stage: str,
        applied: bool = False,
        rejected: bool = False,
        notes: str = "keep-me",
    ):
        from db.bootstrap import ensure_database_ready
        from db.engine import get_session
        from db.models.schema import Job, UserJobState

        ensure_database_ready()
        now = datetime.now(UTC).replace(tzinfo=None)
        with get_session() as session:
            job = Job(
                job_key="pm::co",
                job_key_v2=job_key_v2,
                title="PM",
                company="Co",
                source="instahyre",
                created_at=now,
                updated_at=now,
            )
            session.add(job)
            session.flush()
            session.add(
                UserJobState(
                    job_id=job.id,
                    applied=applied,
                    rejected=rejected,
                    interview=False,
                    offer=False,
                    pipeline_stage=pipeline_stage,
                    notes=notes,
                    updated_at=now,
                )
            )
            session.commit()
            return int(job.id)

    def _upsert_applied(self, job_key_v2: str, *, applied: bool) -> None:
        from db.bootstrap import ensure_database_ready
        from db.engine import get_session
        from db.services.dual_write import _upsert_user_job_state

        ensure_database_ready()
        with get_session() as session:
            _upsert_user_job_state(
                session,
                jobs=[{"JOB_KEY_V2": job_key_v2, "applied": applied}],
                job_id_by_v2={job_key_v2: self._job_ids[job_key_v2]},
            )
            session.commit()

    def _load_state(self, job_key_v2: str):
        from db.engine import get_session
        from db.models.schema import Job, UserJobState

        with get_session() as session:
            job = session.execute(
                select(Job).where(Job.job_key_v2 == job_key_v2)
            ).scalar_one()
            state = session.get(UserJobState, job.id)
            assert state is not None
            return state

    def test_promotes_new_to_applied_on_incoming_applied(self) -> None:
        key = "v2:ih:new-applied"
        self._job_ids = {key: self._seed_job_with_state(job_key_v2=key, pipeline_stage="New")}
        self._upsert_applied(key, applied=True)
        state = self._load_state(key)
        self.assertTrue(state.applied)
        self.assertEqual(state.pipeline_stage, "Applied")

    def test_sets_pipeline_stage_applied_on_promote(self) -> None:
        key = "v2:ih:stage-promote"
        self._job_ids = {key: self._seed_job_with_state(job_key_v2=key, pipeline_stage="New")}
        self._upsert_applied(key, applied=True)
        state = self._load_state(key)
        self.assertEqual(state.pipeline_stage, "Applied")

    def test_preserves_applied_on_incoming_false(self) -> None:
        key = "v2:ih:keep-applied"
        self._job_ids = {
            key: self._seed_job_with_state(
                job_key_v2=key,
                pipeline_stage="Applied",
                applied=True,
            )
        }
        self._upsert_applied(key, applied=False)
        state = self._load_state(key)
        self.assertTrue(state.applied)
        self.assertEqual(state.pipeline_stage, "Applied")

    def test_preserves_interview_on_incoming_applied(self) -> None:
        key = "v2:ih:keep-interview"
        self._job_ids = {
            key: self._seed_job_with_state(
                job_key_v2=key,
                pipeline_stage="Interview",
                applied=True,
            )
        }
        self._upsert_applied(key, applied=True)
        state = self._load_state(key)
        self.assertEqual(state.pipeline_stage, "Interview")

    def test_preserves_rejected_on_incoming_applied(self) -> None:
        key = "v2:ih:keep-rejected"
        self._job_ids = {
            key: self._seed_job_with_state(
                job_key_v2=key,
                pipeline_stage="Rejected",
                rejected=True,
            )
        }
        self._upsert_applied(key, applied=True)
        state = self._load_state(key)
        self.assertEqual(state.pipeline_stage, "Rejected")
        self.assertTrue(state.rejected)

    def test_preserves_saved_on_incoming_applied(self) -> None:
        key = "v2:ih:keep-saved"
        self._job_ids = {
            key: self._seed_job_with_state(
                job_key_v2=key,
                pipeline_stage="Saved",
            )
        }
        self._upsert_applied(key, applied=True)
        state = self._load_state(key)
        self.assertEqual(state.pipeline_stage, "Saved")

    def test_preserves_ghosted_on_incoming_applied(self) -> None:
        key = "v2:ih:keep-ghosted"
        self._job_ids = {
            key: self._seed_job_with_state(
                job_key_v2=key,
                pipeline_stage="Ghosted",
            )
        }
        self._upsert_applied(key, applied=True)
        state = self._load_state(key)
        self.assertEqual(state.pipeline_stage, "Ghosted")

    def test_idempotent_applied_refresh(self) -> None:
        key = "v2:ih:idempotent"
        self._job_ids = {
            key: self._seed_job_with_state(
                job_key_v2=key,
                pipeline_stage="Applied",
                applied=True,
                notes="keep-me",
            )
        }
        self._upsert_applied(key, applied=True)
        state = self._load_state(key)
        self.assertTrue(state.applied)
        self.assertEqual(state.pipeline_stage, "Applied")
        self.assertEqual(state.notes, "keep-me")

    def test_merge_payload_new_insert_applied(self) -> None:
        from db.services.dual_write import _merge_user_job_state_payload

        payload = _merge_user_job_state_payload(
            None,
            {"applied": True},
        )
        self.assertTrue(payload["applied"])
        self.assertEqual(payload["pipeline_stage"], "Applied")


if __name__ == "__main__":
    unittest.main()
