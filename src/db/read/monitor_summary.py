"""Parse lifecycle monitor provider_summary for dashboard display."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from db.services.monitor_governance import count_provider_checks_in_run_window

INSTAHYRE_AUTH_OK_MONITOR_RECONCILIATION = "auth:ok_monitor_reconciliation"


def parse_provider_summary(summary: object) -> dict[str, str]:
    text = str(summary or "").strip()
    if not text:
        return {}
    parsed: dict[str, str] = {}
    for token in text.split(","):
        piece = token.strip()
        if not piece or "=" not in piece:
            continue
        key, value = piece.split("=", 1)
        parsed[key.strip()] = value.strip()
    return parsed


def _summary_int(summary: dict[str, str], key: str) -> int:
    raw = summary.get(key)
    if raw is None:
        return 0
    try:
        return max(0, int(raw))
    except ValueError:
        return 0


def instahyre_monitoring_work_performed_from_summary(summary: dict[str, str]) -> bool:
    """True when provider_summary shows InstaHyre jobs were considered or checked."""
    if _summary_int(summary, "instahyre_backfill_count") > 0:
        return True
    if _summary_int(summary, "instahyre_skipped_limit") > 0:
        return True
    reason = (summary.get("instahyre_auth_probe_reason") or "").strip()
    return reason == INSTAHYRE_AUTH_OK_MONITOR_RECONCILIATION


def _coerce_naive_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if getattr(parsed, "tzinfo", None) is not None:
        parsed = parsed.replace(tzinfo=None)
    return parsed


def instahyre_monitoring_work_performed_in_run(
    run_info: dict[str, object] | None,
    summary: dict[str, str],
    *,
    session: Session | None = None,
) -> bool:
    """True when the latest run performed at least one InstaHyre listing check."""
    if instahyre_monitoring_work_performed_from_summary(summary):
        return True
    if session is None or not run_info:
        return False
    started_at = _coerce_naive_datetime(run_info.get("started_at"))
    completed_at = _coerce_naive_datetime(run_info.get("completed_at"))
    if started_at is None or completed_at is None:
        return False
    return (
        count_provider_checks_in_run_window(
            session,
            "instahyre",
            started_at=started_at,
            completed_at=completed_at,
        )
        > 0
    )


def deferral_counts(summary: object) -> dict[str, int]:
    """Return LinkedIn deferral counters from provider_summary (execution outcomes)."""
    fields = parse_provider_summary(summary)
    counts: dict[str, int] = {}
    for key in (
        "linkedin_skipped_auth",
        "linkedin_skipped_limit",
        "linkedin_skipped_protection",
        "linkedin_skipped_probe_infra",
        "linkedin_skipped_backoff",
        "instahyre_skipped_limit",
    ):
        raw = fields.get(key)
        if raw is None:
            continue
        try:
            counts[key] = int(raw)
        except ValueError:
            continue
    return counts
