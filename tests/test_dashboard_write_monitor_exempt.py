"""CRM write-path monitor_exempt hook tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from db.listing_status import LISTING_STATUS_MONITOR_EXEMPT, LISTING_STATUS_OPEN
from db.models.schema import Base, Job
from db.services.dashboard_write import upsert_user_job_state_from_editor


class MonitorExemptHookTests(unittest.TestCase):
    def setUp(self) -> None:
        self._engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self._engine)
        self._session = Session(self._engine)
        job = Job(
            job_key="legacy",
            job_key_v2="v2-1",
            title="Engineer",
            company="Acme",
            source="linkedin",
            listing_status=LISTING_STATUS_OPEN,
        )
        self._session.add(job)
        self._session.commit()
        self.job_id = int(job.id)

    def tearDown(self) -> None:
        self._session.close()
        self._engine.dispose()

    def test_stage_transition_to_applied_sets_monitor_exempt(self) -> None:
        ok = upsert_user_job_state_from_editor(
            self._session,
            job_key_v2="v2-1",
            pipeline_stage="Applied",
        )
        self.assertTrue(ok)
        self._session.commit()
        job = self._session.get(Job, self.job_id)
        assert job is not None
        self.assertEqual(job.listing_status, LISTING_STATUS_MONITOR_EXEMPT)

    def test_discovery_stage_does_not_set_monitor_exempt(self) -> None:
        ok = upsert_user_job_state_from_editor(
            self._session,
            job_key_v2="v2-1",
            pipeline_stage="Saved",
        )
        self.assertTrue(ok)
        self._session.commit()
        job = self._session.get(Job, self.job_id)
        assert job is not None
        self.assertEqual(job.listing_status, LISTING_STATUS_OPEN)


if __name__ == "__main__":
    unittest.main()
