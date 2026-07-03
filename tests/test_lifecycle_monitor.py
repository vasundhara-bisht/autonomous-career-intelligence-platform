"""Integration tests for lifecycle monitor runtime (T1C)."""

from __future__ import annotations

import io
import os
import sys
import unittest
from contextlib import redirect_stdout
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
for entry in (str(_REPO_ROOT), str(_SRC)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _clear_db_caches() -> None:
    from db.engine import get_engine, get_session_factory

    get_engine.cache_clear()
    get_session_factory.cache_clear()


def _load_fixture(name: str) -> str:
    return (_FIXTURES / name).read_text(encoding="utf-8")


def _auth_ok_probe(_fetcher):
    from monitor.auth_probe import LinkedInAuthProbeResult

    return LinkedInAuthProbeResult(
        auth_health="ok",
        reason="auth:ok",
        probe_url="https://www.linkedin.com/feed/",
    )


def _auth_degraded_probe(_fetcher):
    from monitor.auth_probe import LinkedInAuthProbeResult

    return LinkedInAuthProbeResult(
        auth_health="degraded",
        reason="auth:login_wall",
        probe_url="https://www.linkedin.com/feed/",
    )


def _instahyre_ok_probe(_fetcher):
    from monitor.instahyre_auth_probe import InstaHyreAuthProbeResult

    return InstaHyreAuthProbeResult(
        auth_health="ok",
        reason="auth:ok",
        probe_url="https://www.instahyre.com/candidate/profile/",
    )


def _instahyre_degraded_probe(_fetcher):
    from monitor.instahyre_auth_probe import InstaHyreAuthProbeResult

    return InstaHyreAuthProbeResult(
        auth_health="degraded",
        reason="probe:bot_protection",
        probe_url="https://www.instahyre.com/candidate/profile/",
    )


class LifecycleMonitorRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        import paths

        self._env_patch = {
            "SQLITE_ENABLED": os.environ.get("SQLITE_ENABLED"),
            "AI_JOB_AGENT_DB_PATH": os.environ.get("AI_JOB_AGENT_DB_PATH"),
            "LIFECYCLE_MONITOR_JOB_DELAY_SEC": os.environ.get("LIFECYCLE_MONITOR_JOB_DELAY_SEC"),
            "LIFECYCLE_MONITOR_JITTER_MAX_SEC": os.environ.get("LIFECYCLE_MONITOR_JITTER_MAX_SEC"),
            "LIFECYCLE_MONITOR_LINKEDIN_MAX_PER_RUN": os.environ.get(
                "LIFECYCLE_MONITOR_LINKEDIN_MAX_PER_RUN"
            ),
            "LIFECYCLE_MONITOR_LINKEDIN_MAX_PER_DAY": os.environ.get(
                "LIFECYCLE_MONITOR_LINKEDIN_MAX_PER_DAY"
            ),
            "LIFECYCLE_MONITOR_INSTAHYRE_MAX_PER_RUN": os.environ.get(
                "LIFECYCLE_MONITOR_INSTAHYRE_MAX_PER_RUN"
            ),
            "LIFECYCLE_MONITOR_INSTAHYRE_MAX_PER_DAY": os.environ.get(
                "LIFECYCLE_MONITOR_INSTAHYRE_MAX_PER_DAY"
            ),
        }
        test_dir = paths.ensure_data_dir() / ".test_dbs"
        test_dir.mkdir(parents=True, exist_ok=True)
        self._db_path = test_dir / f"lifecycle_monitor_{os.getpid()}_{id(self)}.db"
        if self._db_path.exists():
            self._db_path.unlink()
        os.environ["AI_JOB_AGENT_DB_PATH"] = str(self._db_path)
        os.environ["SQLITE_ENABLED"] = "1"
        os.environ["LIFECYCLE_MONITOR_JOB_DELAY_SEC"] = "0"
        os.environ["LIFECYCLE_MONITOR_JITTER_MAX_SEC"] = "0"
        os.environ.pop("LIFECYCLE_MONITOR_LINKEDIN_MAX_PER_RUN", None)
        os.environ.pop("LIFECYCLE_MONITOR_LINKEDIN_MAX_PER_DAY", None)
        os.environ.pop("LIFECYCLE_MONITOR_INSTAHYRE_MAX_PER_RUN", None)
        os.environ.pop("LIFECYCLE_MONITOR_INSTAHYRE_MAX_PER_DAY", None)
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

    def _create_job(
        self,
        session,
        *,
        job_key_v2: str,
        source: str = "linkedin",
        link: str = "https://www.linkedin.com/jobs/view/4417376197/",
        listing_status: str = "open",
    ) -> int:
        from db.models.schema import Job

        job = Job(
            job_key=f"k::{job_key_v2}",
            job_key_v2=job_key_v2,
            title="Engineer",
            company="Acme",
            source=source,
            link=link,
            listing_status=listing_status,
        )
        session.add(job)
        session.flush()
        return int(job.id)

    def test_preview_mode_does_not_write_run_records(self) -> None:
        from db.bootstrap import ensure_database_ready
        from db.engine import get_session
        from db.models.schema import LifecycleMonitorRun
        from db.services.lifecycle_monitor import run_lifecycle_monitor
        from sqlalchemy import func, select

        ensure_database_ready()
        with get_session() as session:
            self._create_job(session, job_key_v2="v2:preview-1")
            session.commit()

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            report = run_lifecycle_monitor(get_session, apply=False, limit=5)

        self.assertEqual(report.mode, "preview")
        self.assertEqual(report.cohort_size, 1)
        self.assertIsNone(report.run_id)

        with get_session() as session:
            count = session.execute(select(func.count()).select_from(LifecycleMonitorRun)).scalar_one()
            self.assertEqual(int(count), 0)

        self.assertIn("LIFECYCLE MONITOR PREVIEW", buffer.getvalue())

    def test_apply_mode_commits_per_job_and_finalizes_run(self) -> None:
        from db.bootstrap import ensure_database_ready
        from db.engine import get_session
        from db.models.schema import Job, LifecycleMonitorRun
        from db.services.lifecycle_monitor import run_lifecycle_monitor
        from monitor.browser import PageFetchResult

        ensure_database_ready()
        with get_session() as session:
            open_id = self._create_job(session, job_key_v2="v2:apply-open")
            closed_id = self._create_job(
                session,
                job_key_v2="v2:apply-closed",
                link="https://www.linkedin.com/jobs/view/4417376198/",
            )
            session.commit()

        def fake_fetcher(url: str, source: str) -> PageFetchResult:
            if "4417376198" in url:
                html = _load_fixture("linkedin_job_closed_phrase.html")
            else:
                html = _load_fixture("linkedin_job_open_live_shell.html")
            return PageFetchResult(url=url, html=html, http_status=200, error=None)

        report = run_lifecycle_monitor(
            get_session,
            apply=True,
            limit=10,
            page_fetcher=fake_fetcher,
            auth_probe_runner=_auth_ok_probe,
            instahyre_auth_probe_runner=_instahyre_ok_probe,
            run_parity_checks=False,
        )

        self.assertIsNotNone(report.run_id)
        self.assertEqual(report.auth_health, "ok")
        self.assertEqual(report.checked_count, 2)
        self.assertEqual(report.open_confirmed_count, 1)
        self.assertEqual(report.newly_closed_count, 1)
        self.assertEqual(report.final_status, "completed")

        with get_session() as session:
            open_job = session.get(Job, open_id)
            closed_job = session.get(Job, closed_id)
            run = session.get(LifecycleMonitorRun, report.run_id)
            assert open_job is not None
            assert closed_job is not None
            assert run is not None
            self.assertEqual(open_job.listing_status, "open")
            self.assertIsNotNone(open_job.listing_checked_at)
            self.assertEqual(closed_job.listing_status, "closed")
            self.assertIsNotNone(closed_job.listing_closed_at)
            self.assertEqual(run.status, "completed")
            self.assertEqual(run.checked_count, 2)
            self.assertEqual(run.closed_count, 1)
            self.assertIsNotNone(run.completed_at)
            self.assertEqual(run.auth_health, "ok")
            self.assertIn("instahyre_auth_health=ok", run.provider_summary or "")
            self.assertIn("instahyre_auth_probe_reason=auth:ok", run.provider_summary or "")

    def test_terminal_job_skipped_in_process_job_check(self) -> None:
        from db.bootstrap import ensure_database_ready
        from db.engine import get_session
        from db.models.schema import Job
        from db.services.lifecycle_monitor import process_job_check, utc_now
        from monitor.classifiers.result import ListingClassification

        ensure_database_ready()
        with get_session() as session:
            job_id = self._create_job(
                session,
                job_key_v2="v2:terminal",
                listing_status="removed",
            )
            session.commit()

        with get_session() as session:
            result = process_job_check(
                session,
                job_id=job_id,
                source="linkedin",
                url="https://www.linkedin.com/jobs/view/4417376197/",
                classification=ListingClassification.succeeded("open", "open:live_shell_apply"),
                attempted_at=utc_now(),
            )
            session.commit()

        self.assertTrue(result.skipped)
        self.assertEqual(result.skip_reason, "terminal_state")

        with get_session() as session:
            job = session.get(Job, job_id)
            assert job is not None
            self.assertEqual(job.listing_status, "removed")
            self.assertIsNone(job.listing_checked_at)

    def test_linkedin_applied_status_promotes_discovery_job(self) -> None:
        from db.bootstrap import ensure_database_ready
        from db.engine import get_session
        from db.listing_status import LISTING_STATUS_OPEN, LISTING_STATUS_MONITOR_EXEMPT
        from db.models.schema import Job, UserJobState
        from db.services.lifecycle_monitor import process_job_check, utc_now
        from monitor.classifiers.result import ListingClassification

        ensure_database_ready()
        html = (
            Path(__file__).resolve().parent
            / "fixtures"
            / "linkedin_job_applied_flagship3_submitted.html"
        ).read_text(encoding="utf-8")

        with get_session() as session:
            job = Job(
                job_key="k-applied-promo",
                job_key_v2="v2:linkedin:applied-promo",
                title="PM",
                company="Co",
                link="https://www.linkedin.com/jobs/view/4417376197/",
                source="linkedin",
                listing_status=LISTING_STATUS_OPEN,
            )
            session.add(job)
            session.flush()
            job_id = int(job.id)

            result = process_job_check(
                session,
                job_id=job_id,
                source="linkedin",
                url=job.link,
                classification=ListingClassification.succeeded("open", "open:live_shell_apply"),
                attempted_at=utc_now(),
                html=html,
            )
            session.commit()

        self.assertFalse(result.skipped)
        with get_session() as session:
            job = session.get(Job, job_id)
            state = session.get(UserJobState, job_id)
            assert job is not None and state is not None
            self.assertEqual(state.pipeline_stage, "Applied")
            self.assertTrue(state.applied)
            self.assertEqual(job.listing_status, LISTING_STATUS_MONITOR_EXEMPT)

    def test_stale_running_run_recovered_on_startup(self) -> None:
        from db.bootstrap import ensure_database_ready
        from db.engine import get_session
        from db.models.schema import LifecycleMonitorRun
        from db.services.lifecycle_monitor import recover_stale_monitor_runs, utc_now

        ensure_database_ready()
        stale_started = utc_now() - timedelta(hours=3)
        with get_session() as session:
            run = LifecycleMonitorRun(started_at=stale_started, status="running")
            session.add(run)
            session.commit()
            run_id = int(run.id)

        with get_session() as session:
            recovered = recover_stale_monitor_runs(session, now=utc_now(), threshold_sec=3600)
            session.commit()

        self.assertEqual(recovered, 1)
        with get_session() as session:
            run = session.get(LifecycleMonitorRun, run_id)
            assert run is not None
            self.assertEqual(run.status, "interrupted")
            self.assertIsNotNone(run.completed_at)

    def test_degraded_monitor_health_when_check_failed_rate_high(self) -> None:
        from db.bootstrap import ensure_database_ready
        from db.engine import get_session
        from db.models.schema import LifecycleMonitorRun
        from db.services.lifecycle_monitor import run_lifecycle_monitor
        from monitor.browser import PageFetchResult

        ensure_database_ready()
        with get_session() as session:
            for index in range(3):
                self._create_job(
                    session,
                    job_key_v2=f"v2:fail-{index}",
                    link=f"https://www.linkedin.com/jobs/view/900000000{index}/",
                )
            session.commit()

        def failing_fetcher(url: str, source: str) -> PageFetchResult:
            return PageFetchResult(url=url, html="", http_status=None, error="timeout:goto")

        report = run_lifecycle_monitor(
            get_session,
            apply=True,
            limit=3,
            page_fetcher=failing_fetcher,
            auth_probe_runner=_auth_ok_probe,
            instahyre_auth_probe_runner=_instahyre_ok_probe,
            run_parity_checks=False,
        )

        self.assertEqual(report.check_failed_count, 3)
        self.assertEqual(report.monitor_health, "degraded")
        self.assertEqual(report.systemic_alert, "high_check_failed_rate")

        with get_session() as session:
            run = session.get(LifecycleMonitorRun, report.run_id)
            assert run is not None
            self.assertEqual(run.monitor_health, "degraded")
            self.assertAlmostEqual(float(run.check_failed_rate or 0), 1.0)

    def test_cohort_file_filter(self) -> None:
        from db.bootstrap import ensure_database_ready
        from db.engine import get_session
        from db.services.lifecycle_monitor import run_lifecycle_monitor

        ensure_database_ready()
        with get_session() as session:
            self._create_job(session, job_key_v2="v2:keep")
            self._create_job(session, job_key_v2="v2:drop")
            session.commit()

        cohort_path = self._db_path.parent / f"cohort_{id(self)}.txt"
        cohort_path.write_text("v2:keep\n", encoding="utf-8")
        try:
            report = run_lifecycle_monitor(
                get_session,
                apply=False,
                cohort_file=str(cohort_path),
            )
        finally:
            cohort_path.unlink(missing_ok=True)

        self.assertEqual(report.cohort_size, 1)
        self.assertEqual(report.job_results[0].job_key_v2, "v2:keep")

    def test_cli_preview_exit_code_zero(self) -> None:
        from db.bootstrap import ensure_database_ready
        from db.engine import get_session
        from scripts.run_lifecycle_monitor import main

        ensure_database_ready()
        with get_session() as session:
            self._create_job(session, job_key_v2="v2:cli-preview")
            session.commit()

        with patch("sys.argv", ["run_lifecycle_monitor.py"]):
            self.assertEqual(main([]), 0)

    def test_degraded_auth_blocks_paused_re_admission(self) -> None:
        from db.bootstrap import ensure_database_ready
        from db.engine import get_session
        from db.listing_status import CHECK_FAILED_MAX_CONSECUTIVE
        from db.models.schema import Job
        from db.services.lifecycle_monitor import run_lifecycle_monitor
        from monitor.browser import PageFetchResult

        ensure_database_ready()
        now = datetime.now(UTC).replace(tzinfo=None)
        with get_session() as session:
            job_id = self._create_job(
                session,
                job_key_v2="v2:paused",
                listing_status="check_failed",
            )
            job = session.get(Job, job_id)
            assert job is not None
            job.consecutive_check_failures = CHECK_FAILED_MAX_CONSECUTIVE
            job.listing_check_paused_at = now
            session.commit()

        def fake_fetcher(url: str, source: str) -> PageFetchResult:
            return PageFetchResult(
                url=url,
                html=_load_fixture("linkedin_job_open_live_shell.html"),
                http_status=200,
            )

        report = run_lifecycle_monitor(
            get_session,
            apply=True,
            job_key_v2="v2:paused",
            page_fetcher=fake_fetcher,
            auth_probe_runner=_auth_degraded_probe,
            instahyre_auth_probe_runner=_instahyre_ok_probe,
            run_parity_checks=False,
        )

        self.assertEqual(report.auth_health, "degraded")
        self.assertEqual(report.cohort_size, 0)
        self.assertGreaterEqual(report.skipped_paused_count, 1)
        self.assertEqual(report.checked_count, 0)

    def test_degraded_auth_skips_linkedin_but_checks_instahyre(self) -> None:
        from db.bootstrap import ensure_database_ready
        from db.engine import get_session
        from db.models.schema import Job
        from db.services.lifecycle_monitor import run_lifecycle_monitor
        from monitor.browser import PageFetchResult

        ensure_database_ready()
        with get_session() as session:
            li_id = self._create_job(session, job_key_v2="v2:li-skip")
            ih_id = self._create_job(
                session,
                job_key_v2="v2:ih-keep",
                source="instahyre",
                link="https://www.instahyre.com/job-418799-backend-engineer/",
            )
            session.commit()

        def fake_fetcher(url: str, source: str) -> PageFetchResult:
            if source == "instahyre":
                html = _load_fixture("instahyre_job_open.html")
            else:
                html = _load_fixture("linkedin_job_open_live_shell.html")
            return PageFetchResult(url=url, html=html, http_status=200, error=None)

        report = run_lifecycle_monitor(
            get_session,
            apply=True,
            limit=10,
            page_fetcher=fake_fetcher,
            auth_probe_runner=_auth_degraded_probe,
            instahyre_auth_probe_runner=_instahyre_ok_probe,
            run_parity_checks=False,
        )

        self.assertEqual(report.auth_health, "degraded")
        self.assertEqual(report.linkedin_skipped_auth, 1)
        self.assertEqual(report.checked_count, 1)

        with get_session() as session:
            li_job = session.get(Job, li_id)
            ih_job = session.get(Job, ih_id)
            assert li_job is not None
            assert ih_job is not None
            self.assertIsNone(li_job.listing_checked_at)
            self.assertIsNotNone(ih_job.listing_checked_at)

    def test_instahyre_auth_reconciled_when_probe_degraded_but_jobs_succeed(self) -> None:
        from db.bootstrap import ensure_database_ready
        from db.engine import get_session
        from db.models.schema import Job, LifecycleMonitorRun
        from db.services.lifecycle_monitor import run_lifecycle_monitor
        from monitor.browser import PageFetchResult

        ensure_database_ready()
        with get_session() as session:
            self._create_job(
                session,
                job_key_v2="v2:ih-reconcile",
                source="instahyre",
                link="https://www.instahyre.com/job-418799-backend-engineer/",
            )
            session.commit()

        def fake_fetcher(url: str, source: str) -> PageFetchResult:
            html = _load_fixture("instahyre_job_open.html")
            return PageFetchResult(url=url, html=html, http_status=200, error=None)

        report = run_lifecycle_monitor(
            get_session,
            apply=True,
            limit=10,
            page_fetcher=fake_fetcher,
            auth_probe_runner=_auth_ok_probe,
            instahyre_auth_probe_runner=_instahyre_degraded_probe,
            run_parity_checks=False,
        )

        self.assertEqual(report.instahyre_auth_health, "ok")
        self.assertEqual(report.instahyre_auth_probe_reason, "auth:ok_monitor_reconciliation")
        self.assertEqual(report.checked_count, 1)

        with get_session() as session:
            run = session.get(LifecycleMonitorRun, report.run_id)
            assert run is not None
            self.assertIn("instahyre_auth_health=ok", run.provider_summary or "")
            self.assertIn(
                "instahyre_auth_probe_reason=auth:ok_monitor_reconciliation",
                run.provider_summary or "",
            )

    def test_linkedin_per_run_limit_skips_excess_jobs(self) -> None:
        from db.bootstrap import ensure_database_ready
        from db.engine import get_session
        from db.services.lifecycle_monitor import run_lifecycle_monitor
        from monitor.browser import PageFetchResult

        ensure_database_ready()
        os.environ["LIFECYCLE_MONITOR_LINKEDIN_MAX_PER_RUN"] = "1"

        with get_session() as session:
            for index in range(2):
                self._create_job(
                    session,
                    job_key_v2=f"v2:cap-{index}",
                    link=f"https://www.linkedin.com/jobs/view/880000000{index}/",
                )
            session.commit()

        def fake_fetcher(url: str, source: str) -> PageFetchResult:
            return PageFetchResult(
                url=url,
                html=_load_fixture("linkedin_job_open_live_shell.html"),
                http_status=200,
                error=None,
            )

        report = run_lifecycle_monitor(
            get_session,
            apply=True,
            limit=10,
            page_fetcher=fake_fetcher,
            auth_probe_runner=_auth_ok_probe,
            instahyre_auth_probe_runner=_instahyre_ok_probe,
            run_parity_checks=False,
        )

        self.assertEqual(report.checked_count, 1)
        self.assertEqual(report.linkedin_skipped_limit, 1)

    def test_job_delay_default_is_two_seconds(self) -> None:
        from db.services.lifecycle_monitor import job_delay_sec

        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(job_delay_sec(), 2.0)

    def test_mid_run_protection_aborts_linkedin_without_check_failed(self) -> None:
        from db.bootstrap import ensure_database_ready
        from db.engine import get_session
        from db.listing_status import PROVIDER_HEALTH_PROTECTION, SYSTEMIC_ALERT_PROVIDER_PROTECTION
        from db.models.schema import Job
        from db.services.lifecycle_monitor import run_lifecycle_monitor
        from db.services.provider_state import get_provider_state
        from monitor.auth_probe import LinkedInAuthProbeResult
        from monitor.browser import PageFetchResult

        ensure_database_ready()
        unusual_html = _load_fixture("linkedin_unusual_activity.html")
        open_html = _load_fixture("linkedin_job_open_live_shell.html")

        with get_session() as session:
            li_first = self._create_job(
                session,
                job_key_v2="v2:li-first",
                link="https://www.linkedin.com/jobs/view/4417376197/",
            )
            li_second = self._create_job(
                session,
                job_key_v2="v2:li-second",
                link="https://www.linkedin.com/jobs/view/4417376198/",
            )
            ih_id = self._create_job(
                session,
                job_key_v2="v2:ih-after",
                source="instahyre",
                link="https://www.instahyre.com/job-418799-backend-engineer/",
            )
            session.commit()

        call_count = {"n": 0}

        def fake_fetcher(url: str, source: str) -> PageFetchResult:
            call_count["n"] += 1
            if "feed" in url:
                return PageFetchResult(
                    url=url,
                    html="<html><body><main>Feed content</main></body></html>",
                    http_status=200,
                )
            if source == "linkedin" and "4417376197" in url:
                return PageFetchResult(url=url, html=unusual_html, http_status=200)
            if source == "linkedin":
                return PageFetchResult(url=url, html=open_html, http_status=200)
            return PageFetchResult(
                url=url,
                html=_load_fixture("instahyre_job_open.html"),
                http_status=200,
            )

        report = run_lifecycle_monitor(
            get_session,
            apply=True,
            limit=10,
            page_fetcher=fake_fetcher,
            auth_probe_runner=_auth_ok_probe,
            instahyre_auth_probe_runner=_instahyre_ok_probe,
            run_parity_checks=False,
        )

        self.assertEqual(report.systemic_alert, SYSTEMIC_ALERT_PROVIDER_PROTECTION)
        self.assertEqual(report.protection_reason, "protection:unusual_activity")
        self.assertEqual(report.checked_count, 1)
        self.assertEqual(report.check_failed_count, 0)
        self.assertGreaterEqual(report.linkedin_skipped_protection, 1)

        with get_session() as session:
            first_job = session.get(Job, li_first)
            second_job = session.get(Job, li_second)
            ih_job = session.get(Job, ih_id)
            assert first_job is not None
            assert second_job is not None
            assert ih_job is not None
            self.assertIsNone(first_job.listing_checked_at)
            self.assertIsNone(second_job.listing_checked_at)
            self.assertIsNotNone(ih_job.listing_checked_at)
            row = get_provider_state(session, "linkedin")
            assert row is not None
            self.assertEqual(row.health, PROVIDER_HEALTH_PROTECTION)

    def test_probe_login_wall_degrades_auth_not_protection(self) -> None:
        from db.bootstrap import ensure_database_ready
        from db.engine import get_session
        from db.listing_status import PROVIDER_HEALTH_OK, SYSTEMIC_ALERT_NONE
        from db.services.lifecycle_monitor import run_lifecycle_monitor
        from db.services.provider_state import get_provider_state
        from monitor.browser import PageFetchResult

        ensure_database_ready()
        login_html = "<html><body><h1>Sign in</h1><p>Join LinkedIn</p></body></html>"

        with get_session() as session:
            self._create_job(
                session,
                job_key_v2="v2:li-login",
                link="https://www.linkedin.com/jobs/view/4417376197/",
            )
            session.commit()

        def fake_fetcher(url: str, source: str) -> PageFetchResult:
            if "feed" in url:
                return PageFetchResult(url=url, html=login_html, http_status=200)
            return PageFetchResult(
                url=url,
                html=_load_fixture("linkedin_job_open_live_shell.html"),
                http_status=200,
            )

        report = run_lifecycle_monitor(
            get_session,
            apply=True,
            limit=5,
            page_fetcher=fake_fetcher,
            run_parity_checks=False,
        )

        self.assertEqual(report.auth_health, "degraded")
        self.assertEqual(report.auth_probe_reason, "auth:login_wall")
        self.assertIsNone(report.protection_reason)
        self.assertEqual(report.systemic_alert, SYSTEMIC_ALERT_NONE)
        self.assertGreaterEqual(report.linkedin_skipped_auth, 1)

        with get_session() as session:
            row = get_provider_state(session, "linkedin")
            if row is not None:
                self.assertEqual(row.health, PROVIDER_HEALTH_OK)

    def test_probe_timeout_defers_linkedin_without_auth_degradation(self) -> None:
        from db.bootstrap import ensure_database_ready
        from db.engine import get_session
        from db.listing_status import SYSTEMIC_ALERT_NONE
        from db.services.lifecycle_monitor import run_lifecycle_monitor
        from monitor.browser import PageFetchResult

        ensure_database_ready()

        with get_session() as session:
            self._create_job(
                session,
                job_key_v2="v2:li-timeout",
                link="https://www.linkedin.com/jobs/view/4417376197/",
            )
            ih_id = self._create_job(
                session,
                job_key_v2="v2:ih-timeout",
                source="instahyre",
                link="https://www.instahyre.com/job-418799-backend-engineer/",
            )
            session.commit()

        def fake_fetcher(url: str, source: str) -> PageFetchResult:
            if "feed" in url:
                return PageFetchResult(
                    url=url,
                    html="",
                    http_status=None,
                    error="timeout:goto",
                )
            return PageFetchResult(
                url=url,
                html=_load_fixture("instahyre_job_open.html"),
                http_status=200,
            )

        report = run_lifecycle_monitor(
            get_session,
            apply=True,
            limit=5,
            page_fetcher=fake_fetcher,
            run_parity_checks=False,
        )

        self.assertIsNone(report.auth_health)
        self.assertEqual(report.probe_infra_reason, "timeout:goto")
        self.assertEqual(report.error_summary, "timeout:goto")
        self.assertIsNone(report.protection_reason)
        self.assertEqual(report.systemic_alert, SYSTEMIC_ALERT_NONE)
        self.assertGreaterEqual(report.linkedin_skipped_probe_infra, 1)
        self.assertEqual(report.checked_count, 1)

        with get_session() as session:
            from db.models.schema import Job

            ih_job = session.get(Job, ih_id)
            assert ih_job is not None
            self.assertIsNotNone(ih_job.listing_checked_at)

    def test_probe_unusual_activity_triggers_protection(self) -> None:
        from db.bootstrap import ensure_database_ready
        from db.engine import get_session
        from db.listing_status import PROVIDER_HEALTH_PROTECTION, SYSTEMIC_ALERT_PROVIDER_PROTECTION
        from db.services.lifecycle_monitor import run_lifecycle_monitor
        from db.services.provider_state import get_provider_state
        from monitor.browser import PageFetchResult

        ensure_database_ready()
        unusual_html = _load_fixture("linkedin_unusual_activity.html")

        with get_session() as session:
            self._create_job(
                session,
                job_key_v2="v2:li-probe-protect",
                link="https://www.linkedin.com/jobs/view/4417376197/",
            )
            session.commit()

        def fake_fetcher(url: str, source: str) -> PageFetchResult:
            if "feed" in url:
                return PageFetchResult(url=url, html=unusual_html, http_status=200)
            return PageFetchResult(
                url=url,
                html=_load_fixture("linkedin_job_open_live_shell.html"),
                http_status=200,
            )

        report = run_lifecycle_monitor(
            get_session,
            apply=True,
            limit=5,
            page_fetcher=fake_fetcher,
            run_parity_checks=False,
        )

        self.assertEqual(report.systemic_alert, SYSTEMIC_ALERT_PROVIDER_PROTECTION)
        self.assertEqual(report.protection_reason, "protection:unusual_activity")
        self.assertGreaterEqual(report.linkedin_skipped_protection, 1)

        with get_session() as session:
            row = get_provider_state(session, "linkedin")
            assert row is not None
            self.assertEqual(row.health, PROVIDER_HEALTH_PROTECTION)

    def test_interleaved_queue_checks_mixed_sources(self) -> None:
        from db.bootstrap import ensure_database_ready
        from db.engine import get_session
        from db.services.lifecycle_monitor import run_lifecycle_monitor
        from monitor.browser import PageFetchResult

        ensure_database_ready()
        order: list[str] = []

        with get_session() as session:
            self._create_job(
                session,
                job_key_v2="v2:li-a",
                link="https://www.linkedin.com/jobs/view/4417376197/",
            )
            self._create_job(
                session,
                job_key_v2="v2:ih-a",
                source="instahyre",
                link="https://www.instahyre.com/job-418799-backend-engineer/",
            )
            self._create_job(
                session,
                job_key_v2="v2:li-b",
                link="https://www.linkedin.com/jobs/view/4417376198/",
            )
            session.commit()

        def fake_fetcher(url: str, source: str) -> PageFetchResult:
            if "feed" not in url:
                order.append(source)
            if source == "linkedin":
                return PageFetchResult(
                    url=url,
                    html=_load_fixture("linkedin_job_open_live_shell.html"),
                    http_status=200,
                )
            return PageFetchResult(
                url=url,
                html=_load_fixture("instahyre_job_open.html"),
                http_status=200,
            )

        report = run_lifecycle_monitor(
            get_session,
            apply=True,
            limit=10,
            page_fetcher=fake_fetcher,
            auth_probe_runner=_auth_ok_probe,
            instahyre_auth_probe_runner=_instahyre_ok_probe,
            run_parity_checks=False,
        )

        self.assertEqual(report.checked_count, 3)
        self.assertEqual(order[:3], ["linkedin", "instahyre", "linkedin"])

    def test_active_backoff_defers_linkedin_jobs(self) -> None:
        from db.bootstrap import ensure_database_ready
        from db.engine import get_session
        from db.models.schema import Job, MonitorProviderState
        from db.services.lifecycle_monitor import run_lifecycle_monitor
        from monitor.browser import PageFetchResult

        ensure_database_ready()
        now = datetime.now(UTC).replace(tzinfo=None)

        with get_session() as session:
            self._create_job(
                session,
                job_key_v2="v2:li-backoff",
                link="https://www.linkedin.com/jobs/view/4417376197/",
            )
            ih_id = self._create_job(
                session,
                job_key_v2="v2:ih-backoff",
                source="instahyre",
                link="https://www.instahyre.com/job-418799-backend-engineer/",
            )
            session.add(
                MonitorProviderState(
                    source="linkedin",
                    health="protection",
                    reason="protection:unusual_activity",
                    detected_at=now,
                    backoff_until=now + timedelta(hours=6),
                    consecutive_failures=1,
                    updated_at=now,
                )
            )
            session.commit()

        def fake_fetcher(url: str, source: str) -> PageFetchResult:
            return PageFetchResult(
                url=url,
                html=_load_fixture("instahyre_job_open.html"),
                http_status=200,
            )

        report = run_lifecycle_monitor(
            get_session,
            apply=True,
            limit=10,
            page_fetcher=fake_fetcher,
            auth_probe_runner=_auth_degraded_probe,
            instahyre_auth_probe_runner=_instahyre_ok_probe,
            run_parity_checks=False,
        )

        self.assertGreaterEqual(report.linkedin_skipped_backoff, 1)
        self.assertEqual(report.checked_count, 1)

        with get_session() as session:
            ih_job = session.get(Job, ih_id)
            assert ih_job is not None
            self.assertIsNotNone(ih_job.listing_checked_at)

    def test_budget_exhausted_skip_when_linkedin_daily_cap_hit_and_no_instahyre(self) -> None:
        from db.bootstrap import ensure_database_ready
        from db.engine import get_session
        from db.listing_status import MONITOR_RUN_STATUS_SKIPPED_BUDGET_EXHAUSTED
        from db.models.schema import Job, LifecycleMonitorRun
        from db.services.lifecycle_monitor import run_lifecycle_monitor
        from monitor.browser import PageFetchResult

        os.environ["LIFECYCLE_MONITOR_LINKEDIN_MAX_PER_DAY"] = "1"
        os.environ["LIFECYCLE_MONITOR_LINKEDIN_MAX_PER_RUN"] = "1"

        ensure_database_ready()
        now = datetime.now(UTC).replace(tzinfo=None)
        with get_session() as session:
            job = Job(
                job_key="k::v2:cap",
                job_key_v2="v2:cap",
                title="Engineer",
                company="Acme",
                source="linkedin",
                link="https://www.linkedin.com/jobs/view/4417376197/",
                listing_status="open",
                listing_check_attempted_at=now,
            )
            session.add(job)
            self._create_job(session, job_key_v2="v2:due-1")
            session.commit()

        def fake_fetcher(url: str, source: str) -> PageFetchResult:
            return PageFetchResult(
                url=url,
                html=_load_fixture("linkedin_job_open_live_shell.html"),
                http_status=200,
            )

        report = run_lifecycle_monitor(
            get_session,
            apply=True,
            limit=10,
            page_fetcher=fake_fetcher,
            auth_probe_runner=_auth_ok_probe,
            instahyre_auth_probe_runner=_instahyre_ok_probe,
            run_parity_checks=False,
        )

        self.assertEqual(report.final_status, MONITOR_RUN_STATUS_SKIPPED_BUDGET_EXHAUSTED)
        self.assertEqual(report.monitor_health, "degraded")
        self.assertEqual(report.checked_count, 0)

        with get_session() as session:
            run = session.get(LifecycleMonitorRun, report.run_id)
            assert run is not None
            self.assertEqual(run.status, MONITOR_RUN_STATUS_SKIPPED_BUDGET_EXHAUSTED)


if __name__ == "__main__":
    unittest.main()
