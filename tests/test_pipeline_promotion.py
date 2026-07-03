"""Unit tests for pipeline stage promotion helpers."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
for entry in (str(_REPO_ROOT), str(_SRC)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from db.listing_status import LISTING_STATUS_MONITOR_EXEMPT, LISTING_STATUS_OPEN
from db.models.schema import Base, Job, UserJobState
from db.services.pipeline_promotion import promote_job_to_applied_if_eligible


class PipelinePromotionTests(unittest.TestCase):
    def setUp(self) -> None:
        self._engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self._engine)
        self._session = Session(self._engine)

    def tearDown(self) -> None:
        self._session.close()
        self._engine.dispose()

    def _add_job(
        self,
        *,
        job_key_v2: str,
        pipeline_stage: str | None = None,
        rejected: bool = False,
        notes: str = "keep me",
    ) -> Job:
        job = Job(
            job_key=f"k::{job_key_v2}",
            job_key_v2=job_key_v2,
            title="Engineer",
            company="Acme",
            source="linkedin",
            listing_status=LISTING_STATUS_OPEN,
        )
        self._session.add(job)
        self._session.flush()
        if pipeline_stage is not None:
            self._session.add(
                UserJobState(
                    job_id=job.id,
                    pipeline_stage=pipeline_stage,
                    rejected=rejected,
                    notes=notes,
                )
            )
            self._session.flush()
        return job

    def test_new_promotes_to_applied_and_monitor_exempt(self) -> None:
        job = self._add_job(job_key_v2="v2:new", pipeline_stage="New")
        promoted = promote_job_to_applied_if_eligible(self._session, job)
        self._session.commit()

        self.assertTrue(promoted)
        state = self._session.get(UserJobState, job.id)
        assert state is not None
        self.assertTrue(state.applied)
        self.assertEqual(state.pipeline_stage, "Applied")
        self.assertEqual(state.notes, "keep me")
        refreshed = self._session.get(Job, job.id)
        assert refreshed is not None
        self.assertEqual(refreshed.listing_status, LISTING_STATUS_MONITOR_EXEMPT)

    def test_saved_promotes_to_applied(self) -> None:
        job = self._add_job(job_key_v2="v2:saved", pipeline_stage="Saved")
        promoted = promote_job_to_applied_if_eligible(self._session, job)
        self._session.commit()

        self.assertTrue(promoted)
        state = self._session.get(UserJobState, job.id)
        assert state is not None
        self.assertEqual(state.pipeline_stage, "Applied")

    def test_interview_stage_is_noop(self) -> None:
        job = self._add_job(job_key_v2="v2:interview", pipeline_stage="Interview")
        promoted = promote_job_to_applied_if_eligible(self._session, job)
        self._session.commit()

        self.assertFalse(promoted)
        state = self._session.get(UserJobState, job.id)
        assert state is not None
        self.assertEqual(state.pipeline_stage, "Interview")

    def test_already_applied_is_idempotent_noop(self) -> None:
        job = self._add_job(job_key_v2="v2:applied", pipeline_stage="Applied")
        state = self._session.get(UserJobState, job.id)
        assert state is not None
        state.applied = True
        self._session.flush()
        promoted = promote_job_to_applied_if_eligible(self._session, job)
        self._session.commit()

        self.assertFalse(promoted)

    def test_rejected_discovery_stage_is_noop(self) -> None:
        job = self._add_job(
            job_key_v2="v2:rejected",
            pipeline_stage="New",
            rejected=True,
        )
        promoted = promote_job_to_applied_if_eligible(self._session, job)
        self._session.commit()

        self.assertFalse(promoted)
        state = self._session.get(UserJobState, job.id)
        assert state is not None
        self.assertEqual(state.pipeline_stage, "New")


if __name__ == "__main__":
    unittest.main()
