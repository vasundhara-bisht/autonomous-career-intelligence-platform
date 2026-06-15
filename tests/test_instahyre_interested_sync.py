"""Unit tests for Instahyre Interested synchronization (Phase B)."""

from __future__ import annotations

import os
import sys
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
for entry in (str(_REPO_ROOT), str(_SRC)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from scraper.instahyre import (  # noqa: E402
    OpportunityCard,
    _FEED_ID_INTERESTED_SYNC,
    _build_interested_sync_stub,
    sync_instahyre_interested,
)
from sqlalchemy import func, select, text  # noqa: E402


def _clear_db_caches() -> None:
    from db.engine import get_engine, get_session_factory

    get_engine.cache_clear()
    get_session_factory.cache_clear()


class InterestedSyncStubTests(unittest.TestCase):
    def _card(self, *, job_id: str = "424242") -> OpportunityCard:
        return OpportunityCard(
            job_id=job_id,
            opportunity_url_path=f"/candidate/opportunities/job-{job_id}/",
            canonical_url=(
                f"https://www.instahyre.com/candidate/opportunities/job-{job_id}/"
            ),
            title="Product Manager",
            company="Acme Corp",
            location="Bangalore",
            card_text="Acme Corp - Product Manager",
        )

    def test_stub_sets_applied_and_v2_identity(self) -> None:
        stub = _build_interested_sync_stub(self._card())
        assert stub is not None
        self.assertTrue(stub["applied"])
        self.assertEqual(stub["source"], "instahyre")
        self.assertEqual(stub["JOB_KEY_V2"], "v2:instahyre:424242")
        self.assertEqual(stub["identity_source"], "instahyre_id")
        self.assertEqual(stub["instahyre_job_id"], "424242")
        self.assertEqual(stub["instahyre_feed_id"], _FEED_ID_INTERESTED_SYNC)
        self.assertEqual(stub["instahyre_query_id"], _FEED_ID_INTERESTED_SYNC)
        self.assertEqual(stub["instahyre_query_role"], "state_sync")
        self.assertTrue(stub["currently_active"])

    def test_stub_returns_none_without_job_id(self) -> None:
        card = self._card(job_id="")
        self.assertIsNone(_build_interested_sync_stub(card))


class InterestedSyncHarvestTests(unittest.TestCase):
    @patch("scraper.instahyre._collect_feed_opportunity_cards")
    @patch("scraper.instahyre._assert_candidate_session")
    @patch("scraper.instahyre._ensure_interested_filter_selected")
    @patch("scraper.instahyre._new_authenticated_context")
    @patch("scraper.instahyre.sync_playwright")
    def test_sync_dedupes_by_job_id(
        self,
        mock_playwright,
        mock_new_context,
        _mock_filter,
        _mock_assert,
        mock_collect,
    ) -> None:
        card = OpportunityCard(
            job_id="111",
            opportunity_url_path="/candidate/opportunities/job-111/",
            canonical_url="https://www.instahyre.com/candidate/opportunities/job-111/",
            title="PM",
            company="Co",
            location="India",
            card_text="",
        )
        mock_collect.return_value = ([card, card], {"harvest_mode": "angular_aligned"})

        mock_page = mock_new_context.return_value.new_page.return_value
        mock_browser = mock_playwright.return_value.__enter__.return_value.chromium.launch.return_value
        mock_context = mock_new_context.return_value
        mock_browser  # silence lint

        stubs, stats = sync_instahyre_interested()

        self.assertEqual(len(stubs), 1)
        self.assertEqual(stubs[0]["JOB_KEY_V2"], "v2:instahyre:111")
        self.assertEqual(stats["duplicates_skipped"], 1)
        self.assertEqual(stats["stubs_built"], 1)
        mock_page.goto.assert_called_once()
        mock_context.close.assert_called_once()


class PersistInterestedSyncTests(unittest.TestCase):
    def setUp(self) -> None:
        import paths

        self._env_patch = {
            "SQLITE_ENABLED": os.environ.get("SQLITE_ENABLED"),
            "SQLITE_DUAL_WRITE": os.environ.get("SQLITE_DUAL_WRITE"),
            "AI_JOB_AGENT_DB_PATH": os.environ.get("AI_JOB_AGENT_DB_PATH"),
        }
        test_dir = paths.ensure_data_dir() / ".test_dbs"
        test_dir.mkdir(parents=True, exist_ok=True)
        self._db_path = test_dir / f"interested_sync_{os.getpid()}_{id(self)}.db"
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

    def _stub(self, job_id: str = "999001") -> dict:
        return {
            "title": "PM",
            "company": "Co",
            "location": "India",
            "link": f"https://www.instahyre.com/candidate/opportunities/job-{job_id}/",
            "source": "instahyre",
            "applied": True,
            "JOB_KEY_V2": f"v2:instahyre:{job_id}",
            "identity_source": "instahyre_id",
            "instahyre_job_id": job_id,
            "instahyre_feed_id": _FEED_ID_INTERESTED_SYNC,
            "instahyre_query_id": _FEED_ID_INTERESTED_SYNC,
            "instahyre_query_label": "Instahyre Interested Sync",
            "instahyre_query_role": "state_sync",
            "instahyre_run_ts": datetime.now(UTC).isoformat(),
            "currently_active": True,
        }

    def test_inserts_new_job_as_applied(self) -> None:
        from db.bootstrap import ensure_database_ready
        from db.engine import get_session
        from db.models.schema import AiEvaluation, Job, UserJobState
        from db.services.dual_write import persist_instahyre_interested_sync

        ensure_database_ready()
        report = persist_instahyre_interested_sync([self._stub()])
        self.assertTrue(report["success"])
        self.assertEqual(report["upserted"], 1)
        self.assertEqual(report["state_updated"], 1)
        self.assertEqual(report["not_required_evals_written"], 1)

        with get_session() as session:
            job = session.execute(
                select(Job).where(Job.job_key_v2 == "v2:instahyre:999001")
            ).scalar_one()
            state = session.get(UserJobState, job.id)
            assert state is not None
            self.assertTrue(state.applied)
            self.assertEqual(state.pipeline_stage, "Applied")
            ai_eval = session.execute(
                select(AiEvaluation).where(AiEvaluation.job_id == job.id)
            ).scalar_one()
            self.assertEqual(ai_eval.ai_status, "not_required")
            self.assertIsNone(ai_eval.ai_score)
            self.assertEqual(ai_eval.model, "instahyre_interested_sync")

    def test_promotes_existing_new_to_applied(self) -> None:
        from db.bootstrap import ensure_database_ready
        from db.engine import get_session
        from db.models.schema import Job, UserJobState
        from db.services.dual_write import persist_instahyre_interested_sync

        ensure_database_ready()
        now = datetime.now(UTC).replace(tzinfo=None)
        key = "v2:instahyre:999002"
        with get_session() as session:
            job = Job(
                job_key=key,
                job_key_v2=key,
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
                    applied=False,
                    rejected=False,
                    interview=False,
                    offer=False,
                    pipeline_stage="New",
                    notes="",
                    updated_at=now,
                )
            )
            session.commit()

        report = persist_instahyre_interested_sync([self._stub("999002")])
        self.assertTrue(report["success"])

        with get_session() as session:
            job = session.execute(select(Job).where(Job.job_key_v2 == key)).scalar_one()
            state = session.get(UserJobState, job.id)
            assert state is not None
            self.assertTrue(state.applied)
            self.assertEqual(state.pipeline_stage, "Applied")

    def test_does_not_clobber_existing_scored_eval(self) -> None:
        from db.bootstrap import ensure_database_ready
        from db.engine import get_session
        from db.models.schema import AiEvaluation, Job, UserJobState
        from db.services.dual_write import persist_instahyre_interested_sync

        ensure_database_ready()
        now = datetime.now(UTC).replace(tzinfo=None)
        key = "v2:instahyre:999020"
        with get_session() as session:
            job = Job(
                job_key=key,
                job_key_v2=key,
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
                    applied=True,
                    rejected=False,
                    interview=False,
                    offer=False,
                    pipeline_stage="Applied",
                    notes="",
                    updated_at=now,
                )
            )
            session.add(
                AiEvaluation(
                    job_id=job.id,
                    run_id=None,
                    ai_status="scored",
                    ai_score=8.5,
                    reason="Strong fit",
                    model="runtime_dual_write",
                    evaluated_at=now,
                )
            )
            session.commit()

        report = persist_instahyre_interested_sync([self._stub("999020")])
        self.assertTrue(report["success"])
        self.assertEqual(report["not_required_evals_written"], 0)

        with get_session() as session:
            job = session.execute(select(Job).where(Job.job_key_v2 == key)).scalar_one()
            ai_eval = session.execute(
                select(AiEvaluation).where(AiEvaluation.job_id == job.id)
            ).scalar_one()
            self.assertEqual(ai_eval.ai_status, "scored")
            self.assertEqual(ai_eval.ai_score, 8.5)
            self.assertEqual(ai_eval.reason, "Strong fit")

    def test_preserves_interview_stage(self) -> None:
        from db.bootstrap import ensure_database_ready
        from db.engine import get_session
        from db.models.schema import Job, UserJobState
        from db.services.dual_write import persist_instahyre_interested_sync

        ensure_database_ready()
        now = datetime.now(UTC).replace(tzinfo=None)
        key = "v2:instahyre:999003"
        with get_session() as session:
            job = Job(
                job_key=key,
                job_key_v2=key,
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
                    applied=True,
                    rejected=False,
                    interview=True,
                    offer=False,
                    pipeline_stage="Interview",
                    notes="keep",
                    updated_at=now,
                )
            )
            session.commit()

        report = persist_instahyre_interested_sync([self._stub("999003")])
        self.assertTrue(report["success"])
        self.assertGreaterEqual(report["protected_count"], 1)

        with get_session() as session:
            job = session.execute(select(Job).where(Job.job_key_v2 == key)).scalar_one()
            state = session.get(UserJobState, job.id)
            assert state is not None
            self.assertEqual(state.pipeline_stage, "Interview")
            self.assertEqual(state.notes, "keep")

    def test_skips_rows_without_job_key_v2(self) -> None:
        from db.services.dual_write import persist_instahyre_interested_sync

        report = persist_instahyre_interested_sync(
            [{"title": "X", "company": "Y", "applied": True}]
        )
        self.assertTrue(report["success"])
        self.assertEqual(report["skipped_no_id"], 1)
        self.assertEqual(report["upserted"], 0)

    def test_inserts_observation_for_new_interested_job(self) -> None:
        from db.bootstrap import ensure_database_ready
        from db.engine import get_session
        from db.models.schema import AcquisitionQueryRun, Job, JobObservation
        from db.services.dual_write import persist_instahyre_interested_sync

        ensure_database_ready()
        report = persist_instahyre_interested_sync([self._stub("999010")])
        self.assertTrue(report["success"])
        self.assertEqual(report["observations_written"], 1)
        self.assertIsNotNone(report["sync_run_id"])

        with get_session() as session:
            job = session.execute(
                select(Job).where(Job.job_key_v2 == "v2:instahyre:999010")
            ).scalar_one()
            obs = session.execute(
                select(JobObservation).where(
                    JobObservation.job_id == job.id,
                    JobObservation.run_id == report["sync_run_id"],
                )
            ).scalar_one()
            self.assertTrue(obs.currently_active)
            self.assertEqual(obs.source, "instahyre")
            query_run = session.get(AcquisitionQueryRun, obs.query_run_id)
            assert query_run is not None
            self.assertEqual(query_run.query_id, _FEED_ID_INTERESTED_SYNC)
            self.assertEqual(query_run.query_role, "state_sync")

    def test_historical_view_populated(self) -> None:
        from db.bootstrap import ensure_database_ready
        from db.engine import get_session
        from db.services.dual_write import persist_instahyre_interested_sync

        ensure_database_ready()
        key = "v2:instahyre:999011"
        persist_instahyre_interested_sync([self._stub("999011")])

        with get_session() as session:
            row = session.execute(
                text(
                    """
                    SELECT currently_active, first_seen, last_seen, times_seen
                    FROM historical_jobs_view
                    WHERE JOB_KEY_V2 = :key
                    """
                ),
                {"key": key},
            ).mappings().one()
            self.assertTrue(bool(row["currently_active"]))
            self.assertIsNotNone(row["first_seen"])
            self.assertIsNotNone(row["last_seen"])
            self.assertEqual(int(row["times_seen"]), 1)

    def test_times_seen_increments_on_resync(self) -> None:
        from db.bootstrap import ensure_database_ready
        from db.engine import get_session
        from db.services.dual_write import persist_instahyre_interested_sync

        ensure_database_ready()
        stub = self._stub("999012")
        persist_instahyre_interested_sync([stub])
        persist_instahyre_interested_sync([stub])

        with get_session() as session:
            row = session.execute(
                text(
                    """
                    SELECT times_seen
                    FROM job_observation_stats_view o
                    INNER JOIN jobs j ON j.id = o.job_id
                    WHERE j.job_key_v2 = :key
                    """
                ),
                {"key": "v2:instahyre:999012"},
            ).one()
            self.assertEqual(int(row[0]), 2)

    def test_protected_stage_still_writes_observation(self) -> None:
        from db.bootstrap import ensure_database_ready
        from db.engine import get_session
        from db.models.schema import Job, JobObservation, UserJobState
        from db.services.dual_write import persist_instahyre_interested_sync

        ensure_database_ready()
        now = datetime.now(UTC).replace(tzinfo=None)
        key = "v2:instahyre:999013"
        with get_session() as session:
            job = Job(
                job_key=key,
                job_key_v2=key,
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
                    applied=True,
                    rejected=False,
                    interview=True,
                    offer=False,
                    pipeline_stage="Interview",
                    notes="keep",
                    updated_at=now,
                )
            )
            session.commit()

        report = persist_instahyre_interested_sync([self._stub("999013")])
        self.assertTrue(report["success"])
        self.assertEqual(report["observations_written"], 1)

        with get_session() as session:
            job = session.execute(select(Job).where(Job.job_key_v2 == key)).scalar_one()
            obs_count = session.execute(
                select(func.count())
                .select_from(JobObservation)
                .where(JobObservation.job_id == job.id)
            ).scalar_one()
            self.assertEqual(obs_count, 1)


class InterestedSyncCohortIsolationTests(unittest.TestCase):
    def setUp(self) -> None:
        import paths

        self._env_patch = {
            "SQLITE_ENABLED": os.environ.get("SQLITE_ENABLED"),
            "SQLITE_DUAL_WRITE": os.environ.get("SQLITE_DUAL_WRITE"),
            "AI_JOB_AGENT_DB_PATH": os.environ.get("AI_JOB_AGENT_DB_PATH"),
        }
        test_dir = paths.ensure_data_dir() / ".test_dbs"
        test_dir.mkdir(parents=True, exist_ok=True)
        self._db_path = test_dir / f"interested_cohort_{os.getpid()}_{id(self)}.db"
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

    def test_interested_only_job_excluded_from_export_cohort_after_dual_write(self) -> None:
        from db.bootstrap import ensure_database_ready
        from db.engine import get_session
        from db.read.export_cohort import load_export_cohort_keys, load_latest_run_info
        from db.services.dual_write import (
            dual_write_runtime_snapshot,
            persist_instahyre_interested_sync,
        )

        ensure_database_ready()
        interested_key = "v2:instahyre:888001"
        interested_stub = {
            "title": "Interested Only",
            "company": "Co",
            "location": "India",
            "link": "https://www.instahyre.com/candidate/opportunities/job-888001/",
            "source": "instahyre",
            "applied": True,
            "JOB_KEY_V2": interested_key,
            "identity_source": "instahyre_id",
            "instahyre_feed_id": _FEED_ID_INTERESTED_SYNC,
            "instahyre_query_id": _FEED_ID_INTERESTED_SYNC,
            "instahyre_query_label": "Instahyre Interested Sync",
            "instahyre_query_role": "state_sync",
            "instahyre_run_ts": datetime.now(UTC).isoformat(),
            "currently_active": True,
        }
        sync_report = persist_instahyre_interested_sync([interested_stub])
        sync_run_id = sync_report["sync_run_id"]

        discovery_key = "v2:instahyre:888002"
        discovery_job = {
            "title": "Discovery Job",
            "company": "Acme",
            "location": "India",
            "link": "https://www.instahyre.com/candidate/opportunities/job-888002/",
            "source": "instahyre",
            "JOB_KEY_V2": discovery_key,
            "identity_source": "instahyre_id",
            "instahyre_feed_id": "matching_personalized",
            "instahyre_query_id": "matching_personalized",
            "instahyre_query_label": "Matching Personalized",
            "instahyre_run_ts": datetime.now(UTC).isoformat(),
            "ai_status": "scored",
            "score": 8.0,
            "reason": "fit",
        }
        dual_started = datetime.now(UTC).replace(tzinfo=None)
        dual_write_runtime_snapshot(
            jobs=[discovery_job],
            persistence_cohort_count=1,
            run_started_at=dual_started,
            run_notes="phase_c_runtime_dual_write",
        )

        with get_session() as session:
            latest = load_latest_run_info(session)
            cohort = load_export_cohort_keys(session)
            hist = session.execute(
                text(
                    """
                    SELECT currently_active
                    FROM historical_jobs_view
                    WHERE JOB_KEY_V2 = :key
                    """
                ),
                {"key": interested_key},
            ).mappings().one()

        assert latest is not None
        self.assertNotEqual(latest["run_id"], sync_run_id)
        self.assertEqual(latest["notes"], "phase_c_runtime_dual_write")
        self.assertNotIn(interested_key, cohort)
        self.assertIn(discovery_key, cohort)
        self.assertTrue(bool(hist["currently_active"]))


if __name__ == "__main__":
    unittest.main()
