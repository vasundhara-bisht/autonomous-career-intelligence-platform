"""Tests for monitor governance — budgets, interleave, pacing (OHM Phase 4)."""

from __future__ import annotations

import os
import sys
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
for entry in (str(_REPO_ROOT), str(_SRC)):
    if entry not in sys.path:
        sys.path.insert(0, entry)


def _job(job_key_v2: str, source: str, listing_status: str = "open") -> object:
    from db.services.lifecycle_cohort import MonitorCohortJob

    return MonitorCohortJob(
        job_id=hash(job_key_v2) % 10_000,
        job_key_v2=job_key_v2,
        source=source,
        link=f"https://example.com/{job_key_v2}",
        listing_status=listing_status,
        listing_status_reason=None,
        consecutive_check_failures=0,
        listing_checked_at=None,
        listing_check_paused_at=None,
        pipeline_stage="New",
    )


class MonitorGovernanceUnitTests(unittest.TestCase):
    def test_interleave_round_robin(self) -> None:
        from db.services.monitor_governance import interleave_provider_jobs

        jobs_by_source = {
            "linkedin": [_job("li-1", "linkedin"), _job("li-2", "linkedin")],
            "instahyre": [_job("ih-1", "instahyre")],
        }
        merged = interleave_provider_jobs(jobs_by_source)
        keys = [job.job_key_v2 for job in merged]
        self.assertEqual(keys, ["li-1", "ih-1", "li-2"])

    def test_trim_respects_per_run_cap(self) -> None:
        from db.services.monitor_governance import (
            MonitorGovernanceConfig,
            trim_jobs_for_provider_budget,
        )

        jobs = [_job(f"li-{idx}", "linkedin") for idx in range(5)]
        config = MonitorGovernanceConfig(linkedin_max_per_day=150, linkedin_max_per_run=2)
        kept, skipped = trim_jobs_for_provider_budget(
            jobs,
            source="linkedin",
            config=config,
            daily_used=0,
        )
        self.assertEqual(len(kept), 2)
        self.assertEqual(skipped, 3)

    def test_trim_respects_daily_budget(self) -> None:
        from db.services.monitor_governance import (
            MonitorGovernanceConfig,
            trim_jobs_for_provider_budget,
        )

        jobs = [_job(f"li-{idx}", "linkedin") for idx in range(3)]
        config = MonitorGovernanceConfig(linkedin_max_per_day=150, linkedin_max_per_run=150)
        kept, skipped = trim_jobs_for_provider_budget(
            jobs,
            source="linkedin",
            config=config,
            daily_used=149,
        )
        self.assertEqual(len(kept), 1)
        self.assertEqual(skipped, 2)

    def test_reserved_retry_budget_splits_pools(self) -> None:
        from db.services.monitor_governance import (
            MonitorGovernanceConfig,
            trim_jobs_for_provider_budget,
        )

        jobs = [
            _job("open-1", "linkedin", "open"),
            _job("open-2", "linkedin", "open"),
            _job("retry-1", "linkedin", "check_failed"),
            _job("retry-2", "linkedin", "check_failed"),
        ]
        config = MonitorGovernanceConfig(
            linkedin_max_per_day=150,
            linkedin_max_per_run=3,
            linkedin_reserved_retry_budget=2,
        )
        kept, skipped = trim_jobs_for_provider_budget(
            jobs,
            source="linkedin",
            config=config,
            daily_used=0,
        )
        keys = [job.job_key_v2 for job in kept]
        self.assertEqual(keys, ["open-1", "retry-1", "retry-2"])
        self.assertEqual(skipped, 1)

    def test_reserved_retry_budget_zero_uses_full_pool(self) -> None:
        from db.services.monitor_governance import (
            MonitorGovernanceConfig,
            apply_governance_to_cohort,
        )

        cohort = [
            _job("open-1", "linkedin", "open"),
            _job("retry-1", "linkedin", "check_failed"),
        ]
        config = MonitorGovernanceConfig(
            linkedin_max_per_run=1,
            linkedin_reserved_retry_budget=0,
        )
        result = apply_governance_to_cohort(
            cohort,
            config=config,
            daily_used_by_source={"linkedin": 0, "instahyre": 0},
        )
        self.assertEqual(len(result.jobs), 1)
        self.assertEqual(result.jobs[0].job_key_v2, "open-1")

    def test_exponential_backoff_caps_at_max_hours(self) -> None:
        from db.services.monitor_governance import compute_backoff_until

        detected = datetime(2026, 6, 16, 12, 0, 0)
        first = compute_backoff_until(
            consecutive_failures=1,
            detected_at=detected,
            base_hours=6,
            max_hours=48,
        )
        second = compute_backoff_until(
            consecutive_failures=2,
            detected_at=detected,
            base_hours=6,
            max_hours=48,
        )
        capped = compute_backoff_until(
            consecutive_failures=5,
            detected_at=detected,
            base_hours=6,
            max_hours=48,
        )
        self.assertEqual(first, detected + timedelta(hours=6))
        self.assertEqual(second, detected + timedelta(hours=12))
        self.assertEqual(capped, detected + timedelta(hours=48))

    def test_pacing_delay_uses_provider_override(self) -> None:
        from db.services.monitor_governance import MonitorGovernanceConfig, pacing_delay_sec

        config = MonitorGovernanceConfig(
            job_delay_sec=2.0,
            linkedin_delay_sec=4.0,
            jitter_max_sec=0.0,
        )
        self.assertEqual(pacing_delay_sec("linkedin", config), 4.0)
        self.assertEqual(pacing_delay_sec("instahyre", config), 2.0)

    def test_pacing_delay_adds_jitter(self) -> None:
        import random

        from db.services.monitor_governance import MonitorGovernanceConfig, pacing_delay_sec

        config = MonitorGovernanceConfig(job_delay_sec=2.0, jitter_max_sec=1.0)
        rng = random.Random(0)
        delay = pacing_delay_sec("linkedin", config, rng=rng)
        self.assertGreaterEqual(delay, 2.0)
        self.assertLessEqual(delay, 3.0)

    def test_load_config_from_env(self) -> None:
        from db.services.monitor_governance import load_monitor_governance_config

        with patch.dict(
            os.environ,
            {
                "LIFECYCLE_MONITOR_LINKEDIN_MAX_PER_DAY": "120",
                "LIFECYCLE_MONITOR_LINKEDIN_RESERVED_RETRY_BUDGET": "15",
            },
            clear=False,
        ):
            config = load_monitor_governance_config()
        self.assertEqual(config.linkedin_max_per_day, 120)
        self.assertEqual(config.linkedin_reserved_retry_budget, 15)

    def test_compute_budget_exhausted_skip_eligible_linkedin_only(self) -> None:
        from db.services.monitor_governance import (
            MonitorGovernanceConfig,
            compute_budget_exhausted_skip_eligible,
        )

        cohort = [_job(f"li-{idx}", "linkedin") for idx in range(3)]
        eligible = compute_budget_exhausted_skip_eligible(
            governed_jobs=[],
            original_cohort=cohort,
            config=MonitorGovernanceConfig(),
            daily_used_by_source={"linkedin": 150, "instahyre": 0},
            linkedin_skipped_limit=3,
            instahyre_skipped_limit=0,
            instahyre_backfill_count=0,
        )
        self.assertTrue(eligible)

    def test_compute_budget_exhausted_skip_not_eligible_with_daily_remaining(self) -> None:
        from db.services.monitor_governance import (
            MonitorGovernanceConfig,
            compute_budget_exhausted_skip_eligible,
        )

        cohort = [_job(f"li-{idx}", "linkedin") for idx in range(3)]
        eligible = compute_budget_exhausted_skip_eligible(
            governed_jobs=[],
            original_cohort=cohort,
            config=MonitorGovernanceConfig(),
            daily_used_by_source={"linkedin": 0, "instahyre": 0},
            linkedin_skipped_limit=3,
            instahyre_skipped_limit=0,
            instahyre_backfill_count=0,
        )
        self.assertFalse(eligible)

    def test_build_governed_cohort_backfills_instahyre_when_linkedin_daily_exhausted(self) -> None:
        from unittest.mock import MagicMock

        from db.services.monitor_governance import (
            MonitorGovernanceConfig,
            build_governed_cohort_with_backfill,
        )

        cohort = [_job(f"li-{idx}", "linkedin") for idx in range(5)]
        supplement = [_job(f"ih-{idx}", "instahyre") for idx in range(2)]
        session = MagicMock()
        with patch(
            "db.services.monitor_governance.resolve_monitor_cohort_supplement",
            return_value=supplement,
        ) as mock_supplement:
            result = build_governed_cohort_with_backfill(
                session,
                cohort,
                config=MonitorGovernanceConfig(
                    linkedin_max_per_day=150,
                    linkedin_max_per_run=150,
                    instahyre_max_per_day=500,
                    instahyre_max_per_run=500,
                ),
                daily_used_by_source={"linkedin": 150, "instahyre": 0},
            )

        mock_supplement.assert_called_once()
        self.assertEqual(result.instahyre_backfill_count, 2)
        self.assertEqual(len(result.jobs), 2)
        self.assertEqual(result.jobs[0].source, "instahyre")
        self.assertFalse(result.budget_exhausted_skip_eligible)

    def test_build_governed_cohort_does_not_backfill_when_linkedin_daily_remaining(self) -> None:
        from unittest.mock import MagicMock, patch

        from db.services.monitor_governance import (
            MonitorGovernanceConfig,
            build_governed_cohort_with_backfill,
        )

        cohort = [_job(f"li-{idx}", "linkedin") for idx in range(5)]
        session = MagicMock()
        with patch(
            "db.services.monitor_governance.resolve_monitor_cohort_supplement",
        ) as mock_supplement:
            result = build_governed_cohort_with_backfill(
                session,
                cohort,
                config=MonitorGovernanceConfig(linkedin_max_per_run=2),
                daily_used_by_source={"linkedin": 0, "instahyre": 0},
            )

        mock_supplement.assert_not_called()
        self.assertEqual(len(result.jobs), 2)
        self.assertEqual(result.linkedin_skipped_limit, 3)


class MonitorGovernanceIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        import paths

        self._env_patch = {
            "SQLITE_ENABLED": os.environ.get("SQLITE_ENABLED"),
            "AI_JOB_AGENT_DB_PATH": os.environ.get("AI_JOB_AGENT_DB_PATH"),
        }
        test_dir = paths.ensure_data_dir() / ".test_dbs"
        test_dir.mkdir(parents=True, exist_ok=True)
        self._db_path = test_dir / f"monitor_governance_{os.getpid()}_{id(self)}.db"
        if self._db_path.exists():
            self._db_path.unlink()
        os.environ["AI_JOB_AGENT_DB_PATH"] = str(self._db_path)
        os.environ["SQLITE_ENABLED"] = "1"
        from db.engine import get_engine, get_session_factory

        get_engine.cache_clear()
        get_session_factory.cache_clear()

    def tearDown(self) -> None:
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

    def test_count_provider_checks_today(self) -> None:
        from db.bootstrap import ensure_database_ready
        from db.engine import get_session
        from db.models.schema import Job
        from db.services.monitor_governance import count_provider_checks_today, utc_day_start

        ensure_database_ready()
        today = datetime.now(UTC).replace(tzinfo=None)
        yesterday = today - timedelta(days=1)

        with get_session() as session:
            session.add(
                Job(
                    job_key="k::v2:today",
                    job_key_v2="v2:today",
                    title="PM",
                    company="Acme",
                    source="linkedin",
                    link="https://www.linkedin.com/jobs/view/1",
                    listing_check_attempted_at=today,
                )
            )
            session.add(
                Job(
                    job_key="k::v2:yesterday",
                    job_key_v2="v2:yesterday",
                    title="PM",
                    company="Acme",
                    source="linkedin",
                    link="https://www.linkedin.com/jobs/view/2",
                    listing_check_attempted_at=yesterday,
                )
            )
            session.commit()

        with get_session() as session:
            count = count_provider_checks_today(
                session,
                "linkedin",
                day_start=utc_day_start(today),
            )
        self.assertEqual(count, 1)

    def test_check_after_ist_midnight_counts_on_ist_day(self) -> None:
        from db.bootstrap import ensure_database_ready
        from db.engine import get_session
        from db.models.schema import Job
        from db.services.monitor_governance import budget_day_start, count_provider_checks_today

        ensure_database_ready()
        ref = datetime(2026, 6, 29, 21, 13, tzinfo=UTC).replace(tzinfo=None)
        day_start = budget_day_start(ref)
        attempt_at = datetime(2026, 6, 29, 21, 43, tzinfo=UTC).replace(tzinfo=None)

        with get_session() as session:
            session.add(
                Job(
                    job_key="k::v2:ist-day",
                    job_key_v2="v2:ist-day",
                    title="PM",
                    company="Acme",
                    source="linkedin",
                    link="https://www.linkedin.com/jobs/view/9",
                    listing_check_attempted_at=attempt_at,
                )
            )
            session.commit()

        with get_session() as session:
            count = count_provider_checks_today(
                session,
                "linkedin",
                day_start=day_start,
            )
        self.assertEqual(count, 1)


class BudgetTimezoneTests(unittest.TestCase):
    def test_budget_day_start_uses_ist_midnight(self) -> None:
        from zoneinfo import ZoneInfo

        from db.services.monitor_governance import budget_day_start, budget_timezone

        self.assertEqual(str(budget_timezone()), "Asia/Kolkata")
        ref = datetime(2026, 6, 29, 21, 13, tzinfo=UTC).replace(tzinfo=None)
        start = budget_day_start(ref)
        ist = ZoneInfo("Asia/Kolkata")
        expected = (
            datetime(2026, 6, 30, 0, 0, tzinfo=ist).astimezone(UTC).replace(tzinfo=None)
        )
        self.assertEqual(start, expected)


if __name__ == "__main__":
    unittest.main()
