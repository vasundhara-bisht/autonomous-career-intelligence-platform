"""Scheduler B monitor orchestration — per-job commits, run records (TD3 / T1C)."""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Callable

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from agent.run_trigger import LIFECYCLE_MONITOR_RUN_TRIGGER_ENV, read_run_trigger
from db.listing_status import (
    AUTH_HEALTH_DEGRADED,
    AUTH_HEALTH_OK,
    CHECK_FAILED_RATE_DEGRADED_THRESHOLD,
    LISTING_STATUS_CHECK_FAILED,
    LISTING_STATUS_CLOSED,
    LISTING_STATUS_OPEN,
    LISTING_STATUS_REMOVED,
    MONITOR_HEALTH_DEGRADED,
    MONITOR_HEALTH_OK,
    MONITOR_RUN_STATUS_COMPLETED,
    MONITOR_RUN_STATUS_FAILED,
    MONITOR_RUN_STATUS_INTERRUPTED,
    MONITOR_RUN_STATUS_RUNNING,
    MONITOR_RUN_STATUS_SKIPPED_BUDGET_EXHAUSTED,
    SYSTEMIC_ALERT_HIGH_CHECK_FAILED_RATE,
    SYSTEMIC_ALERT_NONE,
    SYSTEMIC_ALERT_PROVIDER_PROTECTION,
)
from db.models.schema import Job, LifecycleMonitorRun
from db.services.lifecycle_cohort import (
    MONITORED_SOURCES,
    MonitorCohortJob,
    cohort_sql,
    count_monitor_candidates,
    resolve_monitor_cohort,
)
from db.services.lifecycle_write import apply_scheduler_b_outcome, is_terminal_listing_status
from db.services.pipeline_promotion import promote_job_to_applied_if_eligible
from db.services.parity_checks import ListingLifecycleParityReport, check_listing_lifecycle_parity
from db.services.monitor_governance import (
    build_governed_cohort_with_backfill,
    count_provider_checks_today,
    load_monitor_governance_config,
    pacing_delay_sec,
    budget_day_start,
)
from db.services.provider_state import (
    clear_provider_state_on_recovery,
    get_provider_state,
    is_provider_backoff_active,
    record_provider_protection,
)
from monitor.auth_probe import (
    LinkedInAuthProbeResult,
    evaluate_linkedin_auth_probe,
    is_probe_infrastructure_error,
    linkedin_auth_probe_url,
    run_linkedin_auth_probe,
)
from monitor.instahyre_auth_probe import (
    reconcile_instahyre_auth_health,
    run_instahyre_auth_probe,
)
from monitor.browser import MonitorBrowser, PageFetchResult
from monitor.classifiers.instahyre import classify_instahyre_page
from monitor.classifiers.linkedin import classify_linkedin_page, detect_linkedin_user_applied
from monitor.classifiers.linkedin_diagnostics import (
    emit_linkedin_classifier_diagnostic_report,
    linkedin_classifier_debug_enabled,
)
from monitor.classifiers.result import ListingClassification
from monitor.provider_protection import (
    ProviderProtectionResult,
    detect_provider_protection_from_fetch,
)

logger = logging.getLogger(__name__)

PageFetcher = Callable[[str, str], PageFetchResult]

DEFAULT_STALE_RUN_THRESHOLD_SEC = 2 * 60 * 60


@dataclass
class JobCheckResult:
    job_id: int
    job_key_v2: str
    source: str
    prior_status: str
    outcome_status: str
    outcome_reason: str
    applied: bool
    skipped: bool
    skip_reason: str | None = None
    unchanged: bool = False


@dataclass
class MonitorRunReport:
    mode: str
    run_id: int | None = None
    cohort_size: int = 0
    checked_count: int = 0
    open_confirmed_count: int = 0
    newly_closed_count: int = 0
    newly_removed_count: int = 0
    check_failed_count: int = 0
    unchanged_count: int = 0
    skipped_terminal_count: int = 0
    skipped_paused_count: int = 0
    auth_failure_count: int = 0
    duration_sec: float = 0.0
    check_failed_rate: float | None = None
    monitor_health: str | None = None
    systemic_alert: str | None = None
    auth_health: str | None = None
    auth_probe_reason: str | None = None
    error_summary: str | None = None
    final_status: str | None = None
    parity_warning_count: int = 0
    parity_warning_summary: str | None = None
    parity_warnings: list[str] = field(default_factory=list)
    job_results: list[JobCheckResult] = field(default_factory=list)
    linkedin_skipped_auth: int = 0
    linkedin_skipped_limit: int = 0
    linkedin_skipped_protection: int = 0
    linkedin_skipped_probe_infra: int = 0
    linkedin_skipped_backoff: int = 0
    instahyre_skipped_limit: int = 0
    instahyre_backfill_count: int = 0
    pre_governance_candidate_count: int = 0
    budget_exhausted_skip_eligible: bool = False
    protection_reason: str | None = None
    probe_infra_reason: str | None = None
    instahyre_auth_health: str | None = None
    instahyre_auth_probe_reason: str | None = None

    @property
    def linkedin_skipped(self) -> int:
        return (
            self.linkedin_skipped_auth
            + self.linkedin_skipped_limit
            + self.linkedin_skipped_protection
            + self.linkedin_skipped_probe_infra
            + self.linkedin_skipped_backoff
        )

    @property
    def open_count(self) -> int:
        return self.open_confirmed_count

    @property
    def closed_count(self) -> int:
        return self.newly_closed_count

    @property
    def removed_count(self) -> int:
        return self.newly_removed_count


def utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def stale_run_threshold_sec() -> int:
    raw = os.environ.get("LIFECYCLE_MONITOR_STALE_RUN_SEC", "").strip()
    if raw:
        try:
            return max(60, int(raw))
        except ValueError:
            pass
    return DEFAULT_STALE_RUN_THRESHOLD_SEC


def job_delay_sec() -> float:
    return load_monitor_governance_config().job_delay_sec


def linkedin_max_per_run() -> int:
    return load_monitor_governance_config().linkedin_max_per_run


def instahyre_max_per_run() -> int:
    return load_monitor_governance_config().instahyre_max_per_run


def default_apply_limit() -> int | None:
    """Scheduled-wrapper default cohort cap when --limit is omitted (OHM Phase 4)."""
    config = load_monitor_governance_config()
    return max(config.linkedin_max_per_run, config.instahyre_max_per_run)


def linkedin_checks_blocked(auth_health: str | None) -> bool:
    return (auth_health or "").strip().lower() == AUTH_HEALTH_DEGRADED


def should_mark_budget_exhausted_skip(
    report: MonitorRunReport,
    *,
    pre_governance_candidate_count: int,
    budget_exhausted_skip_eligible: bool,
) -> bool:
    """Return True when a run performed no work solely due to daily budget exhaustion."""
    if report.error_summary:
        return False
    if pre_governance_candidate_count <= 0:
        return False
    if report.cohort_size != 0 or report.checked_count != 0:
        return False
    if report.check_failed_count != 0:
        return False
    if (report.auth_health or "").strip().lower() != AUTH_HEALTH_OK:
        return False
    if report.linkedin_skipped_auth > 0:
        return False
    if (
        report.linkedin_skipped_protection > 0
        or report.linkedin_skipped_probe_infra > 0
        or report.linkedin_skipped_backoff > 0
    ):
        return False
    if report.protection_reason or report.probe_infra_reason:
        return False
    if report.linkedin_skipped_limit + report.instahyre_skipped_limit <= 0:
        return False
    return budget_exhausted_skip_eligible


def build_provider_summary(report: MonitorRunReport) -> str | None:
    parts: list[str] = []
    if report.linkedin_skipped_auth:
        parts.append(f"linkedin_skipped_auth={report.linkedin_skipped_auth}")
    if report.linkedin_skipped_limit:
        parts.append(f"linkedin_skipped_limit={report.linkedin_skipped_limit}")
    if report.linkedin_skipped_protection:
        parts.append(f"linkedin_skipped_protection={report.linkedin_skipped_protection}")
    if report.linkedin_skipped_probe_infra:
        parts.append(f"linkedin_skipped_probe_infra={report.linkedin_skipped_probe_infra}")
    if report.linkedin_skipped_backoff:
        parts.append(f"linkedin_skipped_backoff={report.linkedin_skipped_backoff}")
    if report.instahyre_skipped_limit:
        parts.append(f"instahyre_skipped_limit={report.instahyre_skipped_limit}")
    if report.instahyre_backfill_count:
        parts.append(f"instahyre_backfill_count={report.instahyre_backfill_count}")
    if report.protection_reason:
        parts.append(f"protection_reason={report.protection_reason}")
    if report.probe_infra_reason:
        parts.append(f"probe_infra_reason={report.probe_infra_reason}")
    if report.auth_probe_reason:
        parts.append(f"auth_probe_reason={report.auth_probe_reason}")
    if report.instahyre_auth_health:
        parts.append(f"instahyre_auth_health={report.instahyre_auth_health}")
    if report.instahyre_auth_probe_reason:
        parts.append(f"instahyre_auth_probe_reason={report.instahyre_auth_probe_reason}")
    return ",".join(parts) if parts else None


def _evaluate_linkedin_session(
    fetcher: PageFetcher,
    probe_runner,
) -> tuple[LinkedInAuthProbeResult | None, ProviderProtectionResult | None, str | None]:
    """
    Run LinkedIn feed probe: infrastructure failure, then protection, then auth.

    Returns (auth_probe_result, protection_result, probe_infra_reason). At most one
    failure path is set. probe_infra_reason defers LinkedIn without degrading auth.
    """
    if probe_runner is not None and probe_runner is not run_linkedin_auth_probe:
        return probe_runner(fetcher), None, None

    probe_url = linkedin_auth_probe_url()
    probe_fetch = fetcher(probe_url, "linkedin")
    if probe_fetch.error and is_probe_infrastructure_error(probe_fetch.error):
        return None, None, probe_fetch.error

    protection = detect_provider_protection_from_fetch(probe_fetch, source="linkedin")
    if protection.is_protection:
        return None, protection, None

    auth_result = evaluate_linkedin_auth_probe(probe_url=probe_url, fetch=probe_fetch)
    return auth_result, None, None


def _apply_provider_protection_to_report(
    report: MonitorRunReport,
    protection: ProviderProtectionResult,
) -> None:
    report.protection_reason = protection.reason
    report.systemic_alert = SYSTEMIC_ALERT_PROVIDER_PROTECTION
    report.auth_health = AUTH_HEALTH_DEGRADED
    report.auth_probe_reason = protection.reason
    report.monitor_health = MONITOR_HEALTH_DEGRADED


def debug_enabled() -> bool:
    return os.environ.get("DEBUG_LIFECYCLE_MONITOR", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def load_cohort_file(path: str | Path) -> set[str]:
    """Load job_key_v2 values from a newline-delimited cohort file."""
    keys: set[str] = set()
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        keys.add(stripped)
    return keys


def count_paused_monitor_jobs(session: Session) -> int:
    from agent.pipeline_stages import DISCOVERY_PIPELINE_STAGES

    stage_list = ", ".join(f"'{stage}'" for stage in DISCOVERY_PIPELINE_STAGES)
    source_list = ", ".join(f"'{source}'" for source in MONITORED_SOURCES)
    query = f"""
SELECT COUNT(*) FROM jobs j
LEFT JOIN user_job_state u ON u.job_id = j.id
WHERE COALESCE(u.pipeline_stage, 'New') IN ({stage_list})
  AND j.source IN ({source_list})
  AND j.link IS NOT NULL
  AND TRIM(j.link) != ''
  AND j.listing_check_paused_at IS NOT NULL
"""
    return int(session.execute(text(query)).scalar_one())


def recover_stale_monitor_runs(
    session: Session,
    *,
    now: datetime | None = None,
    threshold_sec: int | None = None,
) -> int:
    """Mark long-running monitor runs as interrupted (TD3 stale recovery)."""
    now = now or utc_now()
    threshold = threshold_sec if threshold_sec is not None else stale_run_threshold_sec()
    cutoff = now - timedelta(seconds=threshold)

    stale_rows = session.execute(
        select(LifecycleMonitorRun).where(
            LifecycleMonitorRun.status == MONITOR_RUN_STATUS_RUNNING,
            LifecycleMonitorRun.started_at < cutoff,
        )
    ).scalars().all()

    recovered = 0
    for run in stale_rows:
        run.status = MONITOR_RUN_STATUS_INTERRUPTED
        run.completed_at = now
        run.error_summary = (run.error_summary or "").strip() or "recovered:stale_running"
        recovered += 1
        logger.warning(
            "Recovered stale lifecycle monitor run id=%s started_at=%s",
            run.id,
            run.started_at,
        )
    if recovered:
        session.flush()
    return recovered


def filter_cohort_jobs(
    jobs: list[MonitorCohortJob],
    *,
    job_key_v2: str | None = None,
    source: str | None = None,
    cohort_keys: set[str] | None = None,
) -> list[MonitorCohortJob]:
    filtered = jobs
    if job_key_v2:
        key = job_key_v2.strip()
        filtered = [job for job in filtered if job.job_key_v2 == key]
    if source:
        src = source.strip().lower()
        filtered = [job for job in filtered if job.source.lower() == src]
    if cohort_keys:
        filtered = [job for job in filtered if job.job_key_v2 in cohort_keys]
    return filtered


def classify_page(
    *,
    source: str,
    url: str,
    html: str,
    http_status: int | None,
) -> ListingClassification:
    src = (source or "").strip().lower()
    if src == "linkedin":
        return classify_linkedin_page(url=url, html=html, http_status=http_status)
    if src == "instahyre":
        return classify_instahyre_page(url=url, html=html, http_status=http_status)
    return ListingClassification.check_failed("unsupported_source")


def classification_from_fetch(
    *,
    source: str,
    url: str,
    fetch: PageFetchResult,
) -> ListingClassification:
    if fetch.error:
        return ListingClassification.check_failed(fetch.error)
    return classify_page(
        source=source,
        url=url,
        html=fetch.html,
        http_status=fetch.http_status,
    )


def _record_job_outcome(report: MonitorRunReport, result: JobCheckResult) -> None:
    report.job_results.append(result)
    if result.skipped:
        if result.skip_reason == "terminal_state":
            report.skipped_terminal_count += 1
        return

    report.checked_count += 1
    if result.unchanged:
        report.unchanged_count += 1

    if result.outcome_status == LISTING_STATUS_OPEN:
        report.open_confirmed_count += 1
    elif result.outcome_status == LISTING_STATUS_CLOSED:
        report.newly_closed_count += 1
    elif result.outcome_status == LISTING_STATUS_REMOVED:
        report.newly_removed_count += 1
    elif result.outcome_status == LISTING_STATUS_CHECK_FAILED:
        report.check_failed_count += 1
        if result.outcome_reason.startswith("auth:"):
            report.auth_failure_count += 1


def process_job_check(
    session: Session,
    *,
    job_id: int,
    source: str,
    url: str,
    classification: ListingClassification,
    attempted_at: datetime,
    html: str | None = None,
) -> JobCheckResult:
    job = session.get(Job, job_id)
    if job is None:
        raise ValueError(f"job_not_found:{job_id}")

    prior_status = str(job.listing_status or "")
    if is_terminal_listing_status(prior_status):
        return JobCheckResult(
            job_id=job_id,
            job_key_v2=str(job.job_key_v2 or ""),
            source=source,
            prior_status=prior_status,
            outcome_status=prior_status,
            outcome_reason="",
            applied=False,
            skipped=True,
            skip_reason="terminal_state",
        )

    write_result = apply_scheduler_b_outcome(
        session,
        job,
        listing_status=classification.listing_status,
        listing_status_reason=classification.listing_status_reason,
        attempted_at=attempted_at,
        classification_succeeded=classification.classification_succeeded,
    )

    if (
        source.lower() == "linkedin"
        and classification.classification_succeeded
        and html
        and detect_linkedin_user_applied(html)
    ):
        promote_job_to_applied_if_eligible(session, job)

    outcome_status = str(job.listing_status or "")
    outcome_reason = str(job.listing_status_reason or classification.listing_status_reason or "")
    unchanged = (
        write_result.applied
        and not write_result.skipped
        and prior_status == outcome_status
        and classification.classification_succeeded
    )

    return JobCheckResult(
        job_id=job_id,
        job_key_v2=str(job.job_key_v2 or ""),
        source=source,
        prior_status=prior_status,
        outcome_status=outcome_status,
        outcome_reason=outcome_reason,
        applied=write_result.applied and not write_result.skipped,
        skipped=write_result.skipped,
        skip_reason=write_result.skip_reason,
        unchanged=unchanged,
    )


def open_monitor_run(session: Session, *, started_at: datetime) -> LifecycleMonitorRun:
    run = LifecycleMonitorRun(
        started_at=started_at,
        status=MONITOR_RUN_STATUS_RUNNING,
        run_trigger=read_run_trigger(LIFECYCLE_MONITOR_RUN_TRIGGER_ENV),
    )
    session.add(run)
    session.flush()
    return run


def finalize_monitor_run(
    session: Session,
    run: LifecycleMonitorRun,
    report: MonitorRunReport,
    *,
    completed_at: datetime,
    status: str,
) -> None:
    run.completed_at = completed_at
    run.status = status
    run.cohort_size = report.cohort_size
    run.checked_count = report.checked_count
    run.open_count = report.open_confirmed_count
    run.closed_count = report.newly_closed_count
    run.removed_count = report.newly_removed_count
    run.check_failed_count = report.check_failed_count
    run.paused_skipped_count = report.skipped_paused_count
    run.terminal_skipped_count = report.skipped_terminal_count
    run.duration_sec = report.duration_sec
    run.error_summary = report.error_summary
    run.auth_health = report.auth_health

    if report.systemic_alert == SYSTEMIC_ALERT_PROVIDER_PROTECTION:
        report.monitor_health = MONITOR_HEALTH_DEGRADED
        report.check_failed_rate = (
            report.check_failed_count / report.checked_count
            if report.checked_count > 0
            else None
        )
        run.check_failed_rate = report.check_failed_rate
    elif status == MONITOR_RUN_STATUS_SKIPPED_BUDGET_EXHAUSTED:
        report.check_failed_rate = None
        report.monitor_health = MONITOR_HEALTH_DEGRADED
        report.systemic_alert = SYSTEMIC_ALERT_NONE
        run.check_failed_rate = None
    elif report.checked_count > 0:
        rate = report.check_failed_count / report.checked_count
        report.check_failed_rate = rate
        run.check_failed_rate = rate
        if rate > CHECK_FAILED_RATE_DEGRADED_THRESHOLD:
            report.monitor_health = MONITOR_HEALTH_DEGRADED
            report.systemic_alert = SYSTEMIC_ALERT_HIGH_CHECK_FAILED_RATE
        else:
            report.monitor_health = MONITOR_HEALTH_OK
            report.systemic_alert = SYSTEMIC_ALERT_NONE
    else:
        report.check_failed_rate = None
        if report.systemic_alert != SYSTEMIC_ALERT_PROVIDER_PROTECTION:
            report.monitor_health = MONITOR_HEALTH_OK
            if report.systemic_alert is None:
                report.systemic_alert = SYSTEMIC_ALERT_NONE

    run.monitor_health = report.monitor_health
    run.systemic_alert = report.systemic_alert
    run.provider_summary = build_provider_summary(report)
    run.parity_warning_summary = report.parity_warning_summary
    session.flush()


def record_auth_health_on_run(
    session: Session,
    run_id: int,
    *,
    auth_health: str,
    reason: str,
) -> None:
    run = session.get(LifecycleMonitorRun, run_id)
    if run is None:
        raise RuntimeError(f"monitor_run_not_found:{run_id}")
    run.auth_health = auth_health
    session.flush()
    logger.info(
        "LinkedIn auth probe run_id=%s auth_health=%s reason=%s",
        run_id,
        auth_health,
        reason,
    )


def run_post_apply_parity(
    session_factory: Callable[[], Session],
    report: MonitorRunReport,
) -> ListingLifecycleParityReport:
    """TD9 post-run parity — warning-only; never raises."""
    with session_factory() as session:
        parity = check_listing_lifecycle_parity(session, run_id=report.run_id)

    report.parity_warnings = list(parity.warnings)
    report.parity_warning_count = parity.warning_count
    report.parity_warning_summary = parity.summary_text()

    if report.run_id is not None:
        with session_factory() as session:
            run = session.get(LifecycleMonitorRun, report.run_id)
            if run is not None:
                run.parity_warning_summary = report.parity_warning_summary
                session.commit()

    for warning in parity.warnings:
        logger.warning("TD9 parity: %s", warning)

    return parity


def print_preview_summary(report: MonitorRunReport) -> None:
    print("=== LIFECYCLE MONITOR PREVIEW ===")
    print(f"cohort_selected={report.cohort_size}")
    print(f"paused_skipped={report.skipped_paused_count}")
    if not report.job_results:
        print("jobs=0")
        return
    print("jobs:")
    for item in report.job_results:
        print(
            f"  job_key_v2={item.job_key_v2} source={item.source} "
            f"listing_status={item.prior_status} link_job_id={item.job_id}"
        )


def print_run_summary(report: MonitorRunReport) -> None:
    print("=== LIFECYCLE MONITOR SUMMARY ===")
    print(f"run_id={report.run_id}")
    print(f"status={report.final_status}")
    print(f"cohort_selected={report.cohort_size}")
    print(f"checked={report.checked_count}")
    print(f"  open_confirmed={report.open_confirmed_count}")
    print(f"  newly_closed={report.newly_closed_count}")
    print(f"  newly_removed={report.newly_removed_count}")
    print(f"  check_failed={report.check_failed_count}")
    print(f"  unchanged={report.unchanged_count}")
    print(f"skipped_terminal={report.skipped_terminal_count}")
    print(f"skipped_paused={report.skipped_paused_count}")
    print(f"duration_sec={report.duration_sec:.1f}")
    print(f"auth_health={report.auth_health or 'n/a'}")
    rate_display = (
        f"{report.check_failed_rate:.3f}"
        if report.check_failed_rate is not None
        else "n/a"
    )
    print(f"check_failed_rate={rate_display}")
    print(f"monitor_health={report.monitor_health or 'n/a'}")
    print(f"systemic_alert={report.systemic_alert or 'n/a'}")
    print(f"auth_failure_count={report.auth_failure_count}")
    if report.linkedin_skipped_auth:
        print(f"linkedin_skipped_auth={report.linkedin_skipped_auth}")
    if report.linkedin_skipped_limit:
        print(f"linkedin_skipped_limit={report.linkedin_skipped_limit}")
    if report.linkedin_skipped_protection:
        print(f"linkedin_skipped_protection={report.linkedin_skipped_protection}")
    if report.linkedin_skipped_probe_infra:
        print(f"linkedin_skipped_probe_infra={report.linkedin_skipped_probe_infra}")
    if report.linkedin_skipped_backoff:
        print(f"linkedin_skipped_backoff={report.linkedin_skipped_backoff}")
    if report.instahyre_skipped_limit:
        print(f"instahyre_skipped_limit={report.instahyre_skipped_limit}")
    if report.instahyre_backfill_count:
        print(f"instahyre_backfill_count={report.instahyre_backfill_count}")
    if report.protection_reason:
        print(f"protection_reason={report.protection_reason}")
    if report.linkedin_skipped:
        print(f"linkedin_skipped={report.linkedin_skipped}")
    if report.auth_probe_reason:
        print(f"auth_probe_reason={report.auth_probe_reason}")
    if report.instahyre_auth_health:
        print(f"instahyre_auth_health={report.instahyre_auth_health}")
    if report.instahyre_auth_probe_reason:
        print(f"instahyre_auth_probe_reason={report.instahyre_auth_probe_reason}")
    print(f"parity_warnings={report.parity_warning_count}")
    print(f"parity_warning_summary={report.parity_warning_summary or 'none'}")
    for warning in report.parity_warnings:
        print(f"  PARITY_WARNING: {warning}")
    if report.error_summary:
        print(f"error_summary={report.error_summary}")


def run_lifecycle_monitor(
    session_factory: Callable[[], Session],
    *,
    apply: bool = False,
    limit: int | None = None,
    job_key_v2: str | None = None,
    source: str | None = None,
    cohort_file: str | None = None,
    page_fetcher: PageFetcher | None = None,
    include_paused_check_failed: bool | None = None,
    run_parity_checks: bool = True,
    auth_probe_runner=None,
    instahyre_auth_probe_runner=None,
) -> MonitorRunReport:
    """
    Execute Scheduler B monitor pass.

    Default (apply=False): cohort preview only — no Playwright, no DB writes.
  apply=True: classify cohort jobs, per-job commits (TD3), finalize run record.
    """
    started = time.monotonic()
    now = utc_now()
    mode = "apply" if apply else "preview"
    report = MonitorRunReport(mode=mode)

    cohort_keys = load_cohort_file(cohort_file) if cohort_file else None

    with session_factory() as session:
        recover_stale_monitor_runs(session, now=now)
        session.commit()

    if not apply:
        with session_factory() as session:
            report.skipped_paused_count = count_paused_monitor_jobs(session)
            cohort = resolve_monitor_cohort(session, limit=limit)
            cohort = filter_cohort_jobs(
                cohort,
                job_key_v2=job_key_v2,
                source=source,
                cohort_keys=cohort_keys,
            )
            report.cohort_size = len(cohort)
            report.job_results = [
                JobCheckResult(
                    job_id=job.job_id,
                    job_key_v2=job.job_key_v2,
                    source=job.source,
                    prior_status=job.listing_status,
                    outcome_status=job.listing_status,
                    outcome_reason="",
                    applied=False,
                    skipped=False,
                )
                for job in cohort
            ]
        report.duration_sec = time.monotonic() - started
        print_preview_summary(report)
        return report

    run_id: int | None = None
    with session_factory() as session:
        run = open_monitor_run(session, started_at=now)
        session.commit()
        run_id = int(run.id)
        report.run_id = run_id

    governance = load_monitor_governance_config()
    browser: MonitorBrowser | None = None
    fetcher = page_fetcher

    try:
        if fetcher is None:
            browser = MonitorBrowser()
            browser.__enter__()
            fetcher = browser.fetch_job_page

        probe_runner = auth_probe_runner or run_linkedin_auth_probe
        probe_at = utc_now()
        auth_probe, probe_protection, probe_infra_reason = _evaluate_linkedin_session(
            fetcher,
            probe_runner,
        )

        if probe_infra_reason is not None:
            report.probe_infra_reason = probe_infra_reason
            report.error_summary = probe_infra_reason
            skip_linkedin_protection = False
            skip_linkedin_probe_infra = True
            auth_probe = None
        elif probe_protection is not None and probe_protection.is_protection:
            _apply_provider_protection_to_report(report, probe_protection)
            with session_factory() as session:
                record_provider_protection(
                    session,
                    source="linkedin",
                    reason=probe_protection.reason,
                    detected_at=probe_at,
                    backoff_base_hours=governance.backoff_base_hours,
                    backoff_max_hours=governance.backoff_max_hours,
                )
                record_auth_health_on_run(
                    session,
                    run_id,
                    auth_health=report.auth_health,
                    reason=probe_protection.reason,
                )
                session.commit()
            skip_linkedin_protection = True
            skip_linkedin_probe_infra = False
            auth_probe = None
        else:
            skip_linkedin_protection = False
            skip_linkedin_probe_infra = False
            assert auth_probe is not None
            report.auth_health = auth_probe.auth_health
            report.auth_probe_reason = auth_probe.reason
            with session_factory() as session:
                if auth_probe.auth_health == AUTH_HEALTH_OK:
                    clear_provider_state_on_recovery(
                        session,
                        source="linkedin",
                        recovered_at=probe_at,
                    )
                record_auth_health_on_run(
                    session,
                    run_id,
                    auth_health=auth_probe.auth_health,
                    reason=auth_probe.reason,
                )
                session.commit()

        try:
            instahyre_runner = instahyre_auth_probe_runner or run_instahyre_auth_probe
            instahyre_probe = instahyre_runner(fetcher)
            report.instahyre_auth_health = instahyre_probe.auth_health
            report.instahyre_auth_probe_reason = instahyre_probe.reason
        except ValueError as exc:
            if debug_enabled():
                logger.warning("InstaHyre auth probe skipped: %s", exc)

        admit_paused = (
            include_paused_check_failed
            if include_paused_check_failed is not None
            else auth_probe is not None and auth_probe.auth_health == AUTH_HEALTH_OK
        )
        if not admit_paused and debug_enabled():
            logger.info(
                "Paused check_failed re-admission disabled (auth_health=%s)",
                report.auth_health,
            )

        with session_factory() as session:
            paused_total = count_paused_monitor_jobs(session)
            report.pre_governance_candidate_count = count_monitor_candidates(session)
            cohort = resolve_monitor_cohort(
                session,
                limit=limit,
                include_paused_check_failed=admit_paused,
            )
            cohort = filter_cohort_jobs(
                cohort,
                job_key_v2=job_key_v2,
                source=source,
                cohort_keys=cohort_keys,
            )
            day_start = budget_day_start(now)
            daily_used = {
                provider: count_provider_checks_today(
                    session,
                    provider,
                    day_start=day_start,
                )
                for provider in MONITORED_SOURCES
            }
            governed = build_governed_cohort_with_backfill(
                session,
                cohort,
                config=governance,
                daily_used_by_source=daily_used,
                include_paused_check_failed=admit_paused,
                reference_at=now,
            )
            cohort = governed.jobs
            report.linkedin_skipped_limit += governed.linkedin_skipped_limit
            report.instahyre_skipped_limit += governed.instahyre_skipped_limit
            report.instahyre_backfill_count = governed.instahyre_backfill_count
            report.budget_exhausted_skip_eligible = governed.budget_exhausted_skip_eligible
            report.cohort_size = len(cohort)
            if admit_paused:
                paused_in_cohort = sum(
                    1 for job in cohort if job.listing_check_paused_at is not None
                )
                report.skipped_paused_count = max(0, paused_total - paused_in_cohort)
            else:
                report.skipped_paused_count = paused_total

        with session_factory() as session:
            linkedin_provider_state = get_provider_state(session, "linkedin")
        skip_linkedin_backoff = is_provider_backoff_active(
            linkedin_provider_state,
            now=probe_at,
        ) and not (
            auth_probe is not None and auth_probe.auth_health == AUTH_HEALTH_OK
        )

        linkedin_cap = governance.linkedin_max_per_run
        instahyre_cap = governance.instahyre_max_per_run
        linkedin_checks = 0
        instahyre_checks = 0
        skip_linkedin_auth = (
            not skip_linkedin_protection
            and not skip_linkedin_probe_infra
            and auth_probe is not None
            and linkedin_checks_blocked(auth_probe.auth_health)
        )
        linkedin_aborted = skip_linkedin_protection

        for index, cohort_job in enumerate(cohort):
            if cohort_job.source.lower() == "linkedin":
                if skip_linkedin_probe_infra:
                    report.linkedin_skipped_probe_infra += 1
                    continue
                if skip_linkedin_protection or linkedin_aborted:
                    report.linkedin_skipped_protection += 1
                    continue
                if skip_linkedin_backoff:
                    report.linkedin_skipped_backoff += 1
                    continue
                if skip_linkedin_auth:
                    report.linkedin_skipped_auth += 1
                    continue
                if linkedin_checks >= linkedin_cap:
                    report.linkedin_skipped_limit += 1
                    continue
            elif cohort_job.source.lower() == "instahyre":
                if instahyre_checks >= instahyre_cap:
                    report.instahyre_skipped_limit += 1
                    continue

            attempted_at = utc_now()
            if debug_enabled():
                logger.info(
                    "Checking job_id=%s source=%s status=%s",
                    cohort_job.job_id,
                    cohort_job.source,
                    cohort_job.listing_status,
                )

            fetch = fetcher(cohort_job.link, cohort_job.source)

            if cohort_job.source.lower() == "linkedin":
                job_protection = detect_provider_protection_from_fetch(
                    fetch,
                    source="linkedin",
                )
                if job_protection.is_protection:
                    _apply_provider_protection_to_report(report, job_protection)
                    with session_factory() as session:
                        record_provider_protection(
                            session,
                            source="linkedin",
                            reason=job_protection.reason,
                            detected_at=attempted_at,
                            backoff_base_hours=governance.backoff_base_hours,
                            backoff_max_hours=governance.backoff_max_hours,
                        )
                        session.commit()
                    linkedin_aborted = True
                    logger.warning(
                        "LinkedIn provider protection mid-run job_id=%s reason=%s",
                        cohort_job.job_id,
                        job_protection.reason,
                    )
                    continue

            classification = classification_from_fetch(
                source=cohort_job.source,
                url=cohort_job.link,
                fetch=fetch,
            )
            if (
                linkedin_classifier_debug_enabled()
                and cohort_job.source == "linkedin"
                and fetch.error is None
            ):
                emit_linkedin_classifier_diagnostic_report(
                    job_key_v2=cohort_job.job_key_v2,
                    url=cohort_job.link,
                    html=fetch.html,
                    http_status=fetch.http_status,
                    classification=classification,
                )

            with session_factory() as session:
                result = process_job_check(
                    session,
                    job_id=cohort_job.job_id,
                    source=cohort_job.source,
                    url=cohort_job.link,
                    classification=classification,
                    attempted_at=attempted_at,
                    html=fetch.html,
                )
                session.commit()

            _record_job_outcome(report, result)

            if cohort_job.source.lower() == "linkedin":
                linkedin_checks += 1
            elif cohort_job.source.lower() == "instahyre":
                instahyre_checks += 1

            if index + 1 < len(cohort):
                time.sleep(pacing_delay_sec(cohort_job.source, governance))

        report.duration_sec = time.monotonic() - started
        if should_mark_budget_exhausted_skip(
            report,
            pre_governance_candidate_count=report.pre_governance_candidate_count,
            budget_exhausted_skip_eligible=report.budget_exhausted_skip_eligible,
        ):
            report.final_status = MONITOR_RUN_STATUS_SKIPPED_BUDGET_EXHAUSTED
        else:
            report.final_status = MONITOR_RUN_STATUS_COMPLETED

        report.instahyre_auth_health, report.instahyre_auth_probe_reason = (
            reconcile_instahyre_auth_health(
                instahyre_auth_health=report.instahyre_auth_health,
                instahyre_auth_probe_reason=report.instahyre_auth_probe_reason,
                job_results=report.job_results,
            )
        )

        with session_factory() as session:
            run = session.get(LifecycleMonitorRun, run_id)
            if run is None:
                raise RuntimeError(f"monitor_run_not_found:{run_id}")
            finalize_monitor_run(
                session,
                run,
                report,
                completed_at=utc_now(),
                status=report.final_status,
            )
            session.commit()

        if run_parity_checks:
            run_post_apply_parity(session_factory, report)

        print_run_summary(report)
        return report

    except Exception as exc:
        report.duration_sec = time.monotonic() - started
        report.error_summary = f"{type(exc).__name__}: {exc}"
        report.final_status = MONITOR_RUN_STATUS_FAILED
        logger.exception("Lifecycle monitor run failed")

        if run_id is not None:
            with session_factory() as session:
                run = session.get(LifecycleMonitorRun, run_id)
                if run is not None:
                    finalize_monitor_run(
                        session,
                        run,
                        report,
                        completed_at=utc_now(),
                        status=MONITOR_RUN_STATUS_FAILED,
                    )
                    session.commit()

        print_run_summary(report)
        raise

    finally:
        if browser is not None:
            browser.__exit__(None, None, None)


def cohort_sql_for_tests() -> str:
    """Expose cohort SQL for integration tests."""
    return cohort_sql()
