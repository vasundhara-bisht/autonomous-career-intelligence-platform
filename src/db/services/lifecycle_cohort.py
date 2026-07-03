"""Monitor cohort resolution SQL (§5.1) — data layer for Scheduler B."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from agent.pipeline_stages import DISCOVERY_PIPELINE_STAGES
from db.listing_status import CHECK_FAILED_MAX_CONSECUTIVE, LISTING_STATUS_CHECK_FAILED

MONITORED_SOURCES: tuple[str, ...] = ("linkedin", "instahyre")

INFRASTRUCTURE_FAILURE_PREFIXES: tuple[str, ...] = (
    "fetch:",
    "timeout:",
    "browser:",
    "runtime:",
    "sqlite:",
    "interrupted:",
)
PROVIDER_FAILURE_PREFIXES: tuple[str, ...] = (
    "auth:",
    "protection:",
)

_INFRASTRUCTURE_REASON_SQL = "\n          OR ".join(
    f"j.listing_status_reason LIKE '{prefix}%'" for prefix in INFRASTRUCTURE_FAILURE_PREFIXES
)

_COHORT_SQL = f"""
SELECT
    j.id AS job_id,
    j.job_key_v2 AS job_key_v2,
    j.source AS source,
    j.link AS link,
    j.listing_status AS listing_status,
    j.listing_status_reason AS listing_status_reason,
    j.consecutive_check_failures AS consecutive_check_failures,
    j.listing_checked_at AS listing_checked_at,
    j.listing_check_paused_at AS listing_check_paused_at,
    COALESCE(u.pipeline_stage, 'New') AS pipeline_stage
FROM jobs j
LEFT JOIN user_job_state u ON u.job_id = j.id
LEFT JOIN job_observation_stats_view o ON o.job_id = j.id
WHERE COALESCE(u.pipeline_stage, 'New') IN ({{discovery_stages}})
  AND j.source IN ({{monitored_sources}})
  AND j.link IS NOT NULL
  AND TRIM(j.link) != ''
  AND j.listing_status IN ('open', 'check_failed')
  AND (
    j.listing_status != 'check_failed'
    OR j.consecutive_check_failures < :check_failed_max
  )
  AND j.listing_check_paused_at IS NULL
  AND (
    (
      j.listing_status = 'check_failed'
      AND (
        {_INFRASTRUCTURE_REASON_SQL}
      )
      AND (
        j.listing_check_attempted_at IS NULL
        OR j.listing_check_attempted_at <= datetime(:reference_at, '-' || :t4_interval_hours || ' hours')
      )
    )
    OR (
      j.listing_status = 'open'
      AND (
        j.listing_checked_at IS NULL
        OR (
          (julianday(:reference_at) - julianday(COALESCE(o.first_seen, j.created_at))) <= :t1_max_age_days
          AND j.listing_checked_at IS NOT NULL
          AND j.listing_checked_at <= datetime(:reference_at, '-' || :t1_interval_hours || ' hours')
        )
        OR (
          (julianday(:reference_at) - julianday(COALESCE(o.first_seen, j.created_at))) > :t1_max_age_days
          AND (julianday(:reference_at) - julianday(COALESCE(o.first_seen, j.created_at))) <= :t2_max_age_days
          AND j.listing_checked_at IS NOT NULL
          AND j.listing_checked_at <= datetime(:reference_at, '-' || :t2_interval_hours || ' hours')
        )
        OR (
          (julianday(:reference_at) - julianday(COALESCE(o.first_seen, j.created_at))) > :t2_max_age_days
          AND j.listing_checked_at IS NOT NULL
          AND j.listing_checked_at <= datetime(:reference_at, '-' || :t3_interval_days || ' days')
        )
      )
    )
  )
ORDER BY
    CASE
        WHEN j.listing_status = 'open' AND j.listing_checked_at IS NULL THEN 0
        WHEN j.listing_status = 'open'
          AND (julianday(:reference_at) - julianday(COALESCE(o.first_seen, j.created_at))) <= :t1_max_age_days
          THEN 1
        WHEN j.listing_status = 'open'
          AND (julianday(:reference_at) - julianday(COALESCE(o.first_seen, j.created_at))) <= :t2_max_age_days
          THEN 2
        WHEN j.listing_status = 'open' THEN 3
        WHEN j.listing_status = 'check_failed' THEN 4
        ELSE 5
    END ASC,
    CASE WHEN j.listing_checked_at IS NULL THEN 0 ELSE 1 END ASC,
    j.listing_checked_at ASC,
    j.id ASC
"""


@dataclass(frozen=True)
class MonitorTierConfig:
    """Tier recheck intervals for adaptive cohort eligibility (OHM Phase 3)."""

    t1_max_age_days: int = 7
    t2_max_age_days: int = 30
    t1_interval_hours: int = 24
    t2_interval_hours: int = 72
    t3_interval_days: int = 14
    t4_interval_hours: int = 24


DEFAULT_MONITOR_TIER_CONFIG = MonitorTierConfig()


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def is_infrastructure_check_failed(reason: object) -> bool:
    """Return True when a check_failed reason is infrastructure-only (T4 eligible)."""
    text_value = str(reason or "").strip().lower()
    if not text_value:
        return False
    return any(text_value.startswith(prefix) for prefix in INFRASTRUCTURE_FAILURE_PREFIXES)


def classify_check_failure_class(reason: object) -> str:
    """
    Classify a check_failed reason for diagnostics (OHM Phase 1 interim).

    Returns: infrastructure | provider | ambiguous
    """
    if is_infrastructure_check_failed(reason):
        return "infrastructure"
    text = str(reason or "").strip().lower()
    if not text:
        return "ambiguous"
    for prefix in PROVIDER_FAILURE_PREFIXES:
        if text.startswith(prefix):
            return "provider"
    if text.startswith("dom:"):
        return "provider"
    return "ambiguous"


def eligible_for_recheck(
    *,
    listing_status: object,
    listing_status_reason: object,
    listing_checked_at: datetime | None,
    listing_check_attempted_at: datetime | None,
    first_seen: datetime | None,
    created_at: datetime | None,
    reference_at: datetime,
    tier_config: MonitorTierConfig = DEFAULT_MONITOR_TIER_CONFIG,
) -> bool:
    """Pure predicate mirroring tier eligibility SQL — used by unit tests."""
    status = str(listing_status or "").strip().lower()
    if status == LISTING_STATUS_CHECK_FAILED:
        if not is_infrastructure_check_failed(listing_status_reason):
            return False
        last_attempt = listing_check_attempted_at or listing_checked_at
        if last_attempt is None:
            return True
        return last_attempt <= reference_at - timedelta(hours=tier_config.t4_interval_hours)

    if status != "open":
        return False

    if listing_checked_at is None:
        return True

    anchor = first_seen or created_at
    if anchor is None:
        return True
    age_days = (reference_at - anchor).total_seconds() / 86400.0

    if age_days <= tier_config.t1_max_age_days:
        return listing_checked_at <= reference_at - timedelta(hours=tier_config.t1_interval_hours)
    if age_days <= tier_config.t2_max_age_days:
        return listing_checked_at <= reference_at - timedelta(hours=tier_config.t2_interval_hours)
    return listing_checked_at <= reference_at - timedelta(days=tier_config.t3_interval_days)


@dataclass(frozen=True)
class MonitorCohortJob:
    job_id: int
    job_key_v2: str
    source: str
    link: str
    listing_status: str
    listing_status_reason: str | None
    consecutive_check_failures: int
    listing_checked_at: object
    listing_check_paused_at: object
    pipeline_stage: str


def _discovery_stage_placeholders() -> str:
    return ", ".join(f"'{stage}'" for stage in DISCOVERY_PIPELINE_STAGES)


def _monitored_source_placeholders() -> str:
    return ", ".join(f"'{source}'" for source in MONITORED_SOURCES)


def cohort_sql() -> str:
    """Return the parameterized cohort SQL string (for tests and monitor runtime)."""
    return _COHORT_SQL.format(
        discovery_stages=_discovery_stage_placeholders(),
        monitored_sources=_monitored_source_placeholders(),
    )


def _cohort_params(
    *,
    reference_at: datetime,
    tier_config: MonitorTierConfig,
    limit: int | None = None,
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "check_failed_max": CHECK_FAILED_MAX_CONSECUTIVE,
        "reference_at": reference_at.strftime("%Y-%m-%d %H:%M:%S"),
        "t1_max_age_days": tier_config.t1_max_age_days,
        "t2_max_age_days": tier_config.t2_max_age_days,
        "t1_interval_hours": tier_config.t1_interval_hours,
        "t2_interval_hours": tier_config.t2_interval_hours,
        "t3_interval_days": tier_config.t3_interval_days,
        "t4_interval_hours": tier_config.t4_interval_hours,
    }
    if limit is not None:
        params["limit"] = int(limit)
    return params


def is_in_monitor_cohort(
    *,
    pipeline_stage: object,
    source: object,
    link: object,
    listing_status: object,
    listing_status_reason: object = None,
    consecutive_check_failures: int,
    listing_check_paused_at: object,
    listing_checked_at: datetime | None = None,
    listing_check_attempted_at: datetime | None = None,
    first_seen: datetime | None = None,
    created_at: datetime | None = None,
    reference_at: datetime | None = None,
    tier_config: MonitorTierConfig = DEFAULT_MONITOR_TIER_CONFIG,
) -> bool:
    """Pure predicate mirroring §5.1 base gates + tier eligibility."""
    stage = str(pipeline_stage or "New").strip()
    if stage not in DISCOVERY_PIPELINE_STAGES:
        return False

    src = str(source or "").strip().lower()
    if src not in MONITORED_SOURCES:
        return False

    link_text = str(link or "").strip()
    if not link_text:
        return False

    status = str(listing_status or "").strip().lower()
    if status not in ("open", "check_failed"):
        return False

    if status == LISTING_STATUS_CHECK_FAILED:
        if consecutive_check_failures >= CHECK_FAILED_MAX_CONSECUTIVE:
            return False
        if not is_infrastructure_check_failed(listing_status_reason):
            return False

    if listing_check_paused_at is not None:
        return False

    if reference_at is None:
        return True

    return eligible_for_recheck(
        listing_status=status,
        listing_status_reason=listing_status_reason,
        listing_checked_at=listing_checked_at,
        listing_check_attempted_at=listing_check_attempted_at,
        first_seen=first_seen,
        created_at=created_at,
        reference_at=reference_at,
        tier_config=tier_config,
    )


def resolve_monitor_cohort(
    session: Session,
    *,
    limit: int | None = None,
    include_paused_check_failed: bool = False,
    reference_at: datetime | None = None,
    tier_config: MonitorTierConfig = DEFAULT_MONITOR_TIER_CONFIG,
) -> list[MonitorCohortJob]:
    """
    Load monitor cohort rows ordered per §5.1 adaptive tiers (OHM Phase 3).

    include_paused_check_failed: when True (TD6 auth PASS re-admission path), include
    paused rows that would otherwise be excluded by listing_check_paused_at.
    """
    sql = cohort_sql()
    if include_paused_check_failed:
        sql = sql.replace(
            "  AND j.listing_check_paused_at IS NULL\n",
            "",
        )
    if limit is not None:
        sql = f"{sql}\nLIMIT :limit"

    ref = reference_at or _utc_now()
    params = _cohort_params(reference_at=ref, tier_config=tier_config, limit=limit)

    rows = session.execute(text(sql), params).mappings().all()
    return [
        MonitorCohortJob(
            job_id=int(row["job_id"]),
            job_key_v2=str(row["job_key_v2"] or ""),
            source=str(row["source"] or ""),
            link=str(row["link"] or ""),
            listing_status=str(row["listing_status"] or ""),
            listing_status_reason=(
                str(row["listing_status_reason"])
                if row["listing_status_reason"] is not None
                else None
            ),
            consecutive_check_failures=int(row["consecutive_check_failures"] or 0),
            listing_checked_at=row["listing_checked_at"],
            listing_check_paused_at=row["listing_check_paused_at"],
            pipeline_stage=str(row["pipeline_stage"] or "New"),
        )
        for row in rows
    ]


def _append_cohort_where_clause(sql: str, clause: str) -> str:
    marker = "\nORDER BY"
    idx = sql.index(marker)
    return sql[:idx] + clause + sql[idx:]


def resolve_monitor_cohort_supplement(
    session: Session,
    *,
    source: str,
    exclude_job_ids: set[int],
    limit: int,
    include_paused_check_failed: bool = False,
    reference_at: datetime | None = None,
    tier_config: MonitorTierConfig = DEFAULT_MONITOR_TIER_CONFIG,
) -> list[MonitorCohortJob]:
    """
    Fetch additional tier-ordered monitor jobs for one provider, excluding IDs
  already present in the primary cohort slice (InstaHyre backfill path).
    """
    src = (source or "").strip().lower()
    if src not in MONITORED_SOURCES:
        return []

    sql = cohort_sql()
    if include_paused_check_failed:
        sql = sql.replace(
            "  AND j.listing_check_paused_at IS NULL\n",
            "",
        )

    extra_where = f"\n  AND LOWER(j.source) = :supplement_source\n"
    params_extra: dict[str, Any] = {"supplement_source": src}
    if exclude_job_ids:
        placeholders = ", ".join(
            f":exclude_id_{index}" for index, _ in enumerate(sorted(exclude_job_ids))
        )
        extra_where += f"  AND j.id NOT IN ({placeholders})\n"
        for index, job_id in enumerate(sorted(exclude_job_ids)):
            params_extra[f"exclude_id_{index}"] = int(job_id)

    sql = _append_cohort_where_clause(sql, extra_where)
    sql = f"{sql}\nLIMIT :limit"

    ref = reference_at or _utc_now()
    params = _cohort_params(reference_at=ref, tier_config=tier_config, limit=int(limit))
    params.update(params_extra)

    rows = session.execute(text(sql), params).mappings().all()
    return [
        MonitorCohortJob(
            job_id=int(row["job_id"]),
            job_key_v2=str(row["job_key_v2"] or ""),
            source=str(row["source"] or ""),
            link=str(row["link"] or ""),
            listing_status=str(row["listing_status"] or ""),
            listing_status_reason=(
                str(row["listing_status_reason"])
                if row["listing_status_reason"] is not None
                else None
            ),
            consecutive_check_failures=int(row["consecutive_check_failures"] or 0),
            listing_checked_at=row["listing_checked_at"],
            listing_check_paused_at=row["listing_check_paused_at"],
            pipeline_stage=str(row["pipeline_stage"] or "New"),
        )
        for row in rows
    ]


def count_monitor_candidates(
    session: Session,
    *,
    reference_at: datetime | None = None,
    tier_config: MonitorTierConfig = DEFAULT_MONITOR_TIER_CONFIG,
) -> int:
    ref = reference_at or _utc_now()
    params = _cohort_params(reference_at=ref, tier_config=tier_config)
    rows = session.execute(
        text(f"SELECT COUNT(*) FROM ({cohort_sql()})"),
        params,
    ).scalar_one()
    return int(rows)


def count_monitor_candidates_by_source(
    session: Session,
    source: str,
    *,
    reference_at: datetime | None = None,
    tier_config: MonitorTierConfig = DEFAULT_MONITOR_TIER_CONFIG,
) -> int:
    """Count eligible monitor cohort jobs for one provider (pre-budget cap)."""
    src = (source or "").strip().lower()
    if src not in MONITORED_SOURCES:
        return 0
    sql = _append_cohort_where_clause(cohort_sql(), "\n  AND LOWER(j.source) = :queue_source\n")
    ref = reference_at or _utc_now()
    params = _cohort_params(reference_at=ref, tier_config=tier_config)
    params["queue_source"] = src
    rows = session.execute(
        text(f"SELECT COUNT(*) FROM ({sql})"),
        params,
    ).scalar_one()
    return int(rows)
