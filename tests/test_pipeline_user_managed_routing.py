"""Tests for user-managed pipeline AI routing and not_required semantics."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
_DASHBOARD = _REPO_ROOT / "dashboard"
for entry in (str(_REPO_ROOT), str(_SRC), str(_DASHBOARD)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from agent.historical_persistence import lookup_historical_row  # noqa: E402
from agent.main import (  # noqa: E402
    _historical_job_needs_ai_fallback,
    _historical_pipeline_stage,
    materialize_fully_processed_job,
)
from agent.pipeline_stages import is_user_managed_pipeline_stage  # noqa: E402


def _route_jobs(index: dict, intake: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    fully_processed: list[dict] = []
    needs_ai_only: list[dict] = []
    brand_new: list[dict] = []
    for job in intake:
        row = lookup_historical_row(index, job)
        if not row:
            brand_new.append(job)
            continue
        if is_user_managed_pipeline_stage(_historical_pipeline_stage(row)):
            materialize_fully_processed_job(job, row)
            fully_processed.append(job)
        elif _historical_job_needs_ai_fallback(row):
            needs_ai_only.append(job)
        else:
            materialize_fully_processed_job(job, row)
            fully_processed.append(job)
    return fully_processed, needs_ai_only, brand_new


class HistoricalAiFallbackTests(unittest.TestCase):
    def test_not_required_skips_ai_fallback(self) -> None:
        self.assertFalse(
            _historical_job_needs_ai_fallback(
                {"ai_status": "not_required", "ai_score": "", "reason": ""}
            )
        )

    def test_new_unscored_still_needs_ai(self) -> None:
        self.assertTrue(
            _historical_job_needs_ai_fallback(
                {
                    "ai_status": "pending",
                    "ai_score": "",
                    "reason": "",
                    "pipeline_stage": "New",
                }
            )
        )


class MaterializeAiStatusTests(unittest.TestCase):
    def test_preserves_not_required(self) -> None:
        job = {"title": "PM", "company": "Co"}
        historical = {
            "pipeline_stage": "Applied",
            "ai_status": "not_required",
            "ai_score": "",
            "reason": "",
        }
        materialize_fully_processed_job(job, historical)
        self.assertEqual(job["ai_status"], "not_required")

    def test_user_managed_defensive_not_required(self) -> None:
        job = {"title": "PM", "company": "Co"}
        historical = {
            "pipeline_stage": "Applied",
            "ai_status": "",
            "ai_score": "",
            "reason": "",
        }
        materialize_fully_processed_job(job, historical)
        self.assertEqual(job["ai_status"], "not_required")


class UserManagedRoutingTests(unittest.TestCase):
    def test_applied_null_ai_routes_fully_processed(self) -> None:
        v2 = "v2:instahyre:427332"
        index = {
            "by_v2": {
                v2: {
                    "JOB_KEY_V2": v2,
                    "pipeline_stage": "Applied",
                    "ai_status": "",
                    "ai_score": "",
                    "reason": "",
                }
            },
            "by_legacy": {},
        }
        intake = [{"JOB_KEY_V2": v2, "title": "PM", "company": "Co"}]
        fully_processed, needs_ai_only, brand_new = _route_jobs(index, intake)
        self.assertEqual(len(fully_processed), 1)
        self.assertEqual(len(needs_ai_only), 0)
        self.assertEqual(len(brand_new), 0)
        self.assertEqual(fully_processed[0]["ai_status"], "not_required")

    def test_not_required_routes_fully_processed(self) -> None:
        v2 = "v2:linkedin:co:123"
        index = {
            "by_v2": {
                v2: {
                    "JOB_KEY_V2": v2,
                    "pipeline_stage": "Saved",
                    "ai_status": "not_required",
                    "ai_score": "",
                    "reason": "",
                }
            },
            "by_legacy": {},
        }
        intake = [{"JOB_KEY_V2": v2, "title": "PM", "company": "Co"}]
        fully_processed, needs_ai_only, _brand_new = _route_jobs(index, intake)
        self.assertEqual(len(fully_processed), 1)
        self.assertEqual(len(needs_ai_only), 0)
        self.assertEqual(fully_processed[0]["ai_status"], "not_required")

    def test_new_unscored_still_routes_to_ai(self) -> None:
        v2 = "v2:greenhouse:new:999"
        index = {
            "by_v2": {
                v2: {
                    "JOB_KEY_V2": v2,
                    "pipeline_stage": "New",
                    "ai_status": "pending",
                    "ai_score": "",
                    "reason": "",
                }
            },
            "by_legacy": {},
        }
        intake = [{"JOB_KEY_V2": v2, "title": "PM", "company": "Co"}]
        _fully_processed, needs_ai_only, brand_new = _route_jobs(index, intake)
        self.assertEqual(len(needs_ai_only), 1)
        self.assertEqual(len(brand_new), 0)


class DashboardAiBadgeTests(unittest.TestCase):
    def test_score_badge_not_required(self) -> None:
        from app import score_badge

        self.assertEqual(score_badge(0, "not_required"), "Not Required")

    def test_score_badge_skipped_by_cap(self) -> None:
        from app import score_badge

        self.assertEqual(score_badge(0, "skipped_by_cap"), "Skipped (cap)")

    def test_score_badge_pending(self) -> None:
        from app import score_badge

        self.assertEqual(score_badge(0, "pending"), "Pending AI")

    def test_apply_dashboard_job_ai_columns_not_required(self) -> None:
        import pandas as pd
        from db.read.transforms import apply_dashboard_job_ai_columns

        df = pd.DataFrame(
            [{"ai_status": "not_required", "ai_score": pd.NA, "reason": ""}]
        )
        out = apply_dashboard_job_ai_columns(df)
        self.assertFalse(bool(out.iloc[0]["is_ai_scored"]))
        self.assertEqual(str(out.iloc[0]["ai_status"]), "not_required")


class FeedRediscoveryIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        import os

        import paths

        self._env_patch = {
            "SQLITE_ENABLED": os.environ.get("SQLITE_ENABLED"),
            "SQLITE_DUAL_WRITE": os.environ.get("SQLITE_DUAL_WRITE"),
            "AI_JOB_AGENT_DB_PATH": os.environ.get("AI_JOB_AGENT_DB_PATH"),
        }
        test_dir = paths.ensure_data_dir() / ".test_dbs"
        test_dir.mkdir(parents=True, exist_ok=True)
        self._db_path = test_dir / f"feed_rediscovery_{os.getpid()}_{id(self)}.db"
        if self._db_path.exists():
            self._db_path.unlink()
        os.environ["AI_JOB_AGENT_DB_PATH"] = str(self._db_path)
        os.environ["SQLITE_ENABLED"] = "1"
        os.environ["SQLITE_DUAL_WRITE"] = "1"
        from db.engine import get_engine, get_session_factory

        get_engine.cache_clear()
        get_session_factory.cache_clear()

    def tearDown(self) -> None:
        import os

        from db.engine import get_engine, get_session_factory

        get_engine.cache_clear()
        get_session_factory.cache_clear()
        if self._db_path.exists():
            self._db_path.unlink()
        for key, value in self._env_patch.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_feed_rediscovery_applied_skips_ai_queue(self) -> None:
        from datetime import UTC, datetime

        from db.bootstrap import ensure_database_ready
        from db.read.historical_index import build_historical_index_from_session
        from db.engine import get_session
        from db.services.dual_write import persist_instahyre_interested_sync
        from scraper.instahyre import _FEED_ID_INTERESTED_SYNC

        ensure_database_ready()
        job_id = "777001"
        key = f"v2:instahyre:{job_id}"
        stub = {
            "title": "PM",
            "company": "Co",
            "location": "India",
            "link": f"https://www.instahyre.com/candidate/opportunities/job-{job_id}/",
            "source": "instahyre",
            "applied": True,
            "JOB_KEY_V2": key,
            "identity_source": "instahyre_id",
            "instahyre_feed_id": _FEED_ID_INTERESTED_SYNC,
            "instahyre_query_id": _FEED_ID_INTERESTED_SYNC,
            "instahyre_query_label": "Instahyre Interested Sync",
            "instahyre_query_role": "state_sync",
            "instahyre_run_ts": datetime.now(UTC).isoformat(),
            "currently_active": True,
        }
        report = persist_instahyre_interested_sync([stub])
        self.assertTrue(report["success"])
        self.assertEqual(report["not_required_evals_written"], 1)

        with get_session() as session:
            index = build_historical_index_from_session(session)

        intake = [
            {
                "JOB_KEY_V2": key,
                "title": "PM",
                "company": "Co",
                "link": stub["link"],
                "source": "instahyre",
            }
        ]
        fully_processed, needs_ai_only, brand_new = _route_jobs(index, intake)
        self.assertEqual(len(brand_new), 0)
        self.assertEqual(len(needs_ai_only), 0)
        self.assertEqual(len(fully_processed), 1)
        self.assertEqual(fully_processed[0]["ai_status"], "not_required")


if __name__ == "__main__":
    unittest.main()
