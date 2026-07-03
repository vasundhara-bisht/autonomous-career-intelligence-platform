"""Monitor governance — budgets, pacing, interleave (OHM Phase 4)."""

from __future__ import annotations

import os
import random
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.orm import Session

from db.listing_status import LISTING_STATUS_CHECK_FAILED
from db.services.lifecycle_cohort import (
    MONITORED_SOURCES,
    MonitorCohortJob,
    resolve_monitor_cohort_supplement,
)

DEFAULT_LINKEDIN_MAX_PER_DAY = 150
DEFAULT_LINKEDIN_MAX_PER_RUN = 150
DEFAULT_INSTAHYRE_MAX_PER_DAY = 500
DEFAULT_INSTAHYRE_MAX_PER_RUN = 500
DEFAULT_JOB_DELAY_SEC = 2.0
DEFAULT_JITTER_MAX_SEC = 1.0
DEFAULT_BACKOFF_BASE_HOURS = 6
DEFAULT_BACKOFF_MAX_HOURS = 48
DEFAULT_BUDGET_TIMEZONE = "Asia/Kolkata"


@dataclass(frozen=True)
class MonitorGovernanceConfig:
    linkedin_max_per_day: int = DEFAULT_LINKEDIN_MAX_PER_DAY
    linkedin_max_per_run: int = DEFAULT_LINKEDIN_MAX_PER_RUN
    instahyre_max_per_day: int = DEFAULT_INSTAHYRE_MAX_PER_DAY
    instahyre_max_per_run: int = DEFAULT_INSTAHYRE_MAX_PER_RUN
    job_delay_sec: float = DEFAULT_JOB_DELAY_SEC
    linkedin_delay_sec: float | None = None
    instahyre_delay_sec: float | None = None
    jitter_max_sec: float = DEFAULT_JITTER_MAX_SEC
    backoff_base_hours: int = DEFAULT_BACKOFF_BASE_HOURS
    backoff_max_hours: int = DEFAULT_BACKOFF_MAX_HOURS
    linkedin_reserved_retry_budget: int = 0
    instahyre_reserved_retry_budget: int = 0


@dataclass(frozen=True)
class GovernedCohortResult:
    jobs: list[MonitorCohortJob]
    linkedin_skipped_limit: int = 0
    instahyre_skipped_limit: int = 0
    instahyre_backfill_count: int = 0
    budget_exhausted_skip_eligible: bool = False


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return max(0, int(raw))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return max(0.0, float(raw))
    except ValueError:
        return default


def _env_optional_float(name: str) -> float | None:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        return None


def load_monitor_governance_config() -> MonitorGovernanceConfig:
    """Load Phase 4 governance knobs from environment."""
    return MonitorGovernanceConfig(
        linkedin_max_per_day=_env_int(
            "LIFECYCLE_MONITOR_LINKEDIN_MAX_PER_DAY",
            DEFAULT_LINKEDIN_MAX_PER_DAY,
        ),
        linkedin_max_per_run=_env_int(
            "LIFECYCLE_MONITOR_LINKEDIN_MAX_PER_RUN",
            DEFAULT_LINKEDIN_MAX_PER_RUN,
        ),
        instahyre_max_per_day=_env_int(
            "LIFECYCLE_MONITOR_INSTAHYRE_MAX_PER_DAY",
            DEFAULT_INSTAHYRE_MAX_PER_DAY,
        ),
        instahyre_max_per_run=_env_int(
            "LIFECYCLE_MONITOR_INSTAHYRE_MAX_PER_RUN",
            DEFAULT_INSTAHYRE_MAX_PER_RUN,
        ),
        job_delay_sec=_env_float("LIFECYCLE_MONITOR_JOB_DELAY_SEC", DEFAULT_JOB_DELAY_SEC),
        linkedin_delay_sec=_env_optional_float("LIFECYCLE_MONITOR_LINKEDIN_DELAY_SEC"),
        instahyre_delay_sec=_env_optional_float("LIFECYCLE_MONITOR_INSTAHYRE_DELAY_SEC"),
        jitter_max_sec=_env_float("LIFECYCLE_MONITOR_JITTER_MAX_SEC", DEFAULT_JITTER_MAX_SEC),
        backoff_base_hours=_env_int(
            "LIFECYCLE_MONITOR_LINKEDIN_BACKOFF_BASE_HOURS",
            DEFAULT_BACKOFF_BASE_HOURS,
        ),
        backoff_max_hours=_env_int(
            "LIFECYCLE_MONITOR_LINKEDIN_BACKOFF_MAX_HOURS",
            DEFAULT_BACKOFF_MAX_HOURS,
        ),
        linkedin_reserved_retry_budget=_env_int(
            "LIFECYCLE_MONITOR_LINKEDIN_RESERVED_RETRY_BUDGET",
            0,
        ),
        instahyre_reserved_retry_budget=_env_int(
            "LIFECYCLE_MONITOR_INSTAHYRE_RESERVED_RETRY_BUDGET",
            0,
        ),
    )


def utc_day_start(reference_at: datetime | None = None) -> datetime:
    now = reference_at or datetime.now(UTC).replace(tzinfo=None)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def budget_timezone() -> ZoneInfo:
    """Timezone for daily monitor budget boundaries (scheduler operator day)."""
    raw = os.environ.get("LIFECYCLE_MONITOR_BUDGET_TZ", DEFAULT_BUDGET_TIMEZONE).strip()
    if not raw:
        raw = DEFAULT_BUDGET_TIMEZONE
    try:
        return ZoneInfo(raw)
    except Exception:
        return ZoneInfo(DEFAULT_BUDGET_TIMEZONE)


def budget_day_start(reference_at: datetime | None = None) -> datetime:
    """
    Start of the current budget day in LIFECYCLE_MONITOR_BUDGET_TZ, as UTC-naive
    for comparison with listing_check_attempted_at (stored UTC-naive).
    """
    tz = budget_timezone()
    if reference_at is None:
        local_now = datetime.now(tz)
    else:
        ref = reference_at
        if ref.tzinfo is None:
            ref = ref.replace(tzinfo=UTC)
        local_now = ref.astimezone(tz)
    local_midnight = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    return local_midnight.astimezone(UTC).replace(tzinfo=None)


def count_provider_checks_today(
    session: Session,
    source: str,
    *,
    day_start: datetime | None = None,
) -> int:
    """Count listing checks attempted today for a provider (daily budget usage)."""
    src = (source or "").strip().lower()
    start = day_start or budget_day_start()
    count = session.execute(
        text(
            """
            SELECT COUNT(*) FROM jobs
            WHERE LOWER(source) = :source
              AND listing_check_attempted_at IS NOT NULL
              AND listing_check_attempted_at >= :day_start
            """
        ),
        {"source": src, "day_start": start.strftime("%Y-%m-%d %H:%M:%S")},
    ).scalar_one()
    return int(count)


def count_provider_checks_in_run_window(
    session: Session,
    source: str,
    *,
    started_at: datetime,
    completed_at: datetime,
) -> int:
    """Count listing checks attempted for a provider during a monitor run window."""
    src = (source or "").strip().lower()
    count = session.execute(
        text(
            """
            SELECT COUNT(*) FROM jobs
            WHERE LOWER(source) = :source
              AND listing_check_attempted_at IS NOT NULL
              AND listing_check_attempted_at >= :started_at
              AND listing_check_attempted_at <= :completed_at
            """
        ),
        {
            "source": src,
            "started_at": started_at.strftime("%Y-%m-%d %H:%M:%S"),
            "completed_at": completed_at.strftime("%Y-%m-%d %H:%M:%S"),
        },
    ).scalar_one()
    return int(count)


def compute_backoff_until(
    *,
    consecutive_failures: int,
    detected_at: datetime,
    base_hours: int,
    max_hours: int,
) -> datetime:
    """Exponential protection backoff capped at max_hours."""
    failures = max(1, int(consecutive_failures))
    hours = min(int(base_hours) * (2 ** (failures - 1)), int(max_hours))
    return detected_at + timedelta(hours=hours)


def _provider_caps(config: MonitorGovernanceConfig, source: str) -> tuple[int, int]:
    src = source.lower()
    if src == "linkedin":
        return config.linkedin_max_per_day, config.linkedin_max_per_run
    if src == "instahyre":
        return config.instahyre_max_per_day, config.instahyre_max_per_run
    return 0, 0


def provider_daily_remaining(
    config: MonitorGovernanceConfig,
    source: str,
    daily_used: int,
) -> int:
    max_per_day, _ = _provider_caps(config, source)
    return max(0, max_per_day - int(daily_used))


def compute_budget_exhausted_skip_eligible(
    *,
    governed_jobs: list[MonitorCohortJob],
    original_cohort: list[MonitorCohortJob],
    config: MonitorGovernanceConfig,
    daily_used_by_source: dict[str, int],
    linkedin_skipped_limit: int,
    instahyre_skipped_limit: int,
    instahyre_backfill_count: int,
) -> bool:
    """True when governed cohort is empty solely due to daily budget exhaustion."""
    if governed_jobs:
        return False
    if linkedin_skipped_limit + instahyre_skipped_limit <= 0:
        return False

    by_source: dict[str, list[MonitorCohortJob]] = defaultdict(list)
    for job in original_cohort:
        by_source[job.source.lower()].append(job)

    linkedin_jobs = by_source.get("linkedin", [])
    instahyre_jobs = by_source.get("instahyre", [])
    instahyre_considered = len(instahyre_jobs) + int(instahyre_backfill_count)

    if linkedin_jobs:
        li_remaining = provider_daily_remaining(
            config,
            "linkedin",
            daily_used_by_source.get("linkedin", 0),
        )
        if li_remaining > 0:
            return False

    if instahyre_considered > 0:
        ih_remaining = provider_daily_remaining(
            config,
            "instahyre",
            daily_used_by_source.get("instahyre", 0),
        )
        if ih_remaining > 0:
            return False
        return True

    if linkedin_jobs and instahyre_considered == 0:
        return provider_daily_remaining(
            config,
            "linkedin",
            daily_used_by_source.get("linkedin", 0),
        ) == 0

    return False


def _reserved_retry_budget(config: MonitorGovernanceConfig, source: str) -> int:
    src = source.lower()
    if src == "linkedin":
        return config.linkedin_reserved_retry_budget
    if src == "instahyre":
        return config.instahyre_reserved_retry_budget
    return 0


def trim_jobs_for_provider_budget(
    jobs: list[MonitorCohortJob],
    *,
    source: str,
    config: MonitorGovernanceConfig,
    daily_used: int,
) -> tuple[list[MonitorCohortJob], int]:
    """
    Trim a provider-ordered job list to remaining daily + per-run budget.

    Optional reserved retry pool (Pillar D): when enabled, caps T4 infra retries
    separately without changing freshness-first ordering within each pool.
    """
    max_per_day, max_per_run = _provider_caps(config, source)
    daily_remaining = max(0, max_per_day - int(daily_used))
    run_cap = min(max_per_run, daily_remaining)
    if run_cap <= 0 or not jobs:
        return [], len(jobs)

    reserved = _reserved_retry_budget(config, source)
    if reserved > 0:
        freshness_jobs = [
            job for job in jobs if str(job.listing_status or "").lower() != LISTING_STATUS_CHECK_FAILED
        ]
        retry_jobs = [
            job for job in jobs if str(job.listing_status or "").lower() == LISTING_STATUS_CHECK_FAILED
        ]
        retry_cap = min(reserved, run_cap, len(retry_jobs))
        fresh_cap = min(max(0, run_cap - retry_cap), len(freshness_jobs))
        kept = freshness_jobs[:fresh_cap] + retry_jobs[:retry_cap]
        return kept, len(jobs) - len(kept)

    kept = jobs[:run_cap]
    return kept, len(jobs) - len(kept)


def interleave_provider_jobs(
    jobs_by_source: dict[str, list[MonitorCohortJob]],
    *,
    sources: tuple[str, ...] = MONITORED_SOURCES,
) -> list[MonitorCohortJob]:
    """Round-robin merge across providers preserving within-provider tier order."""
    indices = {source: 0 for source in sources}
    merged: list[MonitorCohortJob] = []
    while True:
        added = False
        for source in sources:
            bucket = jobs_by_source.get(source, [])
            idx = indices[source]
            if idx < len(bucket):
                merged.append(bucket[idx])
                indices[source] = idx + 1
                added = True
        if not added:
            break
    return merged


def build_governed_cohort_with_backfill(
    session: Session,
    cohort: list[MonitorCohortJob],
    *,
    config: MonitorGovernanceConfig,
    daily_used_by_source: dict[str, int],
    include_paused_check_failed: bool = False,
    reference_at: datetime | None = None,
) -> GovernedCohortResult:
    """
    Apply per-provider budgets, backfill InstaHyre when LinkedIn daily budget is
    exhausted, then interleave (minimal Run-27 fix without redesigning cohort SQL).
    """
    by_source: dict[str, list[MonitorCohortJob]] = defaultdict(list)
    for job in cohort:
        by_source[job.source.lower()].append(job)

    linkedin_jobs = by_source.get("linkedin", [])
    instahyre_jobs = list(by_source.get("instahyre", []))

    kept_linkedin, linkedin_skipped = trim_jobs_for_provider_budget(
        linkedin_jobs,
        source="linkedin",
        config=config,
        daily_used=daily_used_by_source.get("linkedin", 0),
    )

    instahyre_backfill_count = 0
    linkedin_daily_remaining = provider_daily_remaining(
        config,
        "linkedin",
        daily_used_by_source.get("linkedin", 0),
    )
    if (
        linkedin_daily_remaining == 0
        and linkedin_jobs
        and not kept_linkedin
    ):
        instahyre_daily_remaining = provider_daily_remaining(
            config,
            "instahyre",
            daily_used_by_source.get("instahyre", 0),
        )
        backfill_limit = min(config.instahyre_max_per_run, instahyre_daily_remaining)
        if backfill_limit > 0:
            exclude_ids = {job.job_id for job in cohort}
            supplement = resolve_monitor_cohort_supplement(
                session,
                source="instahyre",
                exclude_job_ids=exclude_ids,
                limit=backfill_limit,
                include_paused_check_failed=include_paused_check_failed,
                reference_at=reference_at,
            )
            instahyre_backfill_count = len(supplement)
            instahyre_jobs.extend(supplement)

    kept_instahyre, instahyre_skipped = trim_jobs_for_provider_budget(
        instahyre_jobs,
        source="instahyre",
        config=config,
        daily_used=daily_used_by_source.get("instahyre", 0),
    )

    jobs = interleave_provider_jobs(
        {"linkedin": kept_linkedin, "instahyre": kept_instahyre},
    )
    budget_exhausted_skip_eligible = compute_budget_exhausted_skip_eligible(
        governed_jobs=jobs,
        original_cohort=cohort,
        config=config,
        daily_used_by_source=daily_used_by_source,
        linkedin_skipped_limit=linkedin_skipped,
        instahyre_skipped_limit=instahyre_skipped,
        instahyre_backfill_count=instahyre_backfill_count,
    )

    return GovernedCohortResult(
        jobs=jobs,
        linkedin_skipped_limit=linkedin_skipped,
        instahyre_skipped_limit=instahyre_skipped,
        instahyre_backfill_count=instahyre_backfill_count,
        budget_exhausted_skip_eligible=budget_exhausted_skip_eligible,
    )


def apply_governance_to_cohort(
    cohort: list[MonitorCohortJob],
    *,
    config: MonitorGovernanceConfig,
    daily_used_by_source: dict[str, int],
) -> GovernedCohortResult:
    """Apply per-provider budget caps then interleave (Pillars A, C, optional D)."""
    by_source: dict[str, list[MonitorCohortJob]] = defaultdict(list)
    for job in cohort:
        by_source[job.source.lower()].append(job)

    trimmed: dict[str, list[MonitorCohortJob]] = {}
    linkedin_skipped = 0
    instahyre_skipped = 0
    for source in MONITORED_SOURCES:
        source_jobs = by_source.get(source, [])
        kept, skipped = trim_jobs_for_provider_budget(
            source_jobs,
            source=source,
            config=config,
            daily_used=daily_used_by_source.get(source, 0),
        )
        trimmed[source] = kept
        if source == "linkedin":
            linkedin_skipped = skipped
        elif source == "instahyre":
            instahyre_skipped = skipped

    return GovernedCohortResult(
        jobs=interleave_provider_jobs(trimmed),
        linkedin_skipped_limit=linkedin_skipped,
        instahyre_skipped_limit=instahyre_skipped,
    )


def pacing_delay_sec(
    source: str,
    config: MonitorGovernanceConfig,
    *,
    rng: random.Random | None = None,
) -> float:
    """Per-provider pacing delay with optional jitter (Pillar B)."""
    src = (source or "").strip().lower()
    if src == "linkedin" and config.linkedin_delay_sec is not None:
        base = config.linkedin_delay_sec
    elif src == "instahyre" and config.instahyre_delay_sec is not None:
        base = config.instahyre_delay_sec
    else:
        base = config.job_delay_sec
    if config.jitter_max_sec <= 0:
        return base
    jitter_rng = rng or random
    return base + jitter_rng.uniform(0.0, config.jitter_max_sec)
