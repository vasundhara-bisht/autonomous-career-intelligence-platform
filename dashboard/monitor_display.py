"""Product-friendly labels for Operational Monitor Health (dashboard-only)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from db.read.monitor_provider_metrics import ProviderMonitorSnapshot

_MONITOR_HEALTH_LABELS: dict[str, str] = {
    "ok": "Healthy",
    "degraded": "Degraded",
}

_AUTH_HEALTH_LABELS: dict[str, str] = {
    "ok": "Connected",
    "degraded": "Needs attention",
}

_PROVIDER_HEALTH_LABELS: dict[str, str] = {
    "ok": "Healthy",
    "degraded": "Rate limited",
    "protection": "Protection active",
}

_SYSTEMIC_ALERT_LABELS: dict[str, str] = {
    "none": "None",
    "high_check_failed_rate": "High failure rate",
    "provider_protection": "Protection detected",
}

_RUN_STATUS_LABELS: dict[str, str] = {
    "completed": "Completed",
    "failed": "Failed",
    "interrupted": "Interrupted",
    "running": "Running",
    "skipped_budget_exhausted": "Skipped (Budget Exhausted)",
}

_SCHEDULER_STATE_LABELS: dict[str, str] = {
    "not_loaded": "Not loaded",
    "not_installed": "Not installed",
    "running": "Running",
    "unknown": "Unknown",
}

_DEFERRAL_LABELS: dict[str, str] = {
    "linkedin_skipped_auth": "LinkedIn skipped (authentication)",
    "linkedin_skipped_limit": "LinkedIn skipped (daily limit)",
    "linkedin_skipped_protection": "LinkedIn skipped (protection)",
    "linkedin_skipped_probe_infra": "LinkedIn skipped (probe infrastructure)",
    "linkedin_skipped_backoff": "LinkedIn skipped (backoff)",
    "instahyre_skipped_limit": "InstaHyre skipped (daily limit)",
}

_LINKEDIN_RUN_ISSUE_LABELS: dict[str, str] = {
    "linkedin_skipped_auth": "login not available",
    "linkedin_skipped_limit": "daily limit reached",
    "linkedin_skipped_protection": "LinkedIn protection pause",
    "linkedin_skipped_probe_infra": "temporary check issue",
    "linkedin_skipped_backoff": "waiting before retry",
}

_INSTAHYRE_RUN_ISSUE_LABELS: dict[str, str] = {
    "instahyre_skipped_limit": "daily limit reached",
}

_REASON_PREFIX_LABELS: dict[str, str] = {
    "auth": "Login",
    "protection": "Protection",
    "probe_infra": "Check issue",
    "timeout": "Timeout",
    "browser": "Browser",
    "runtime": "Runtime",
    "fetch": "Fetch",
    "dom": "Page check",
}


def _title_case_words(text: str) -> str:
    return " ".join(word.capitalize() for word in text.replace("_", " ").split())


def present_monitor_health(value: object) -> str:
    key = str(value or "").strip().lower()
    if not key or key == "—":
        return "—"
    return _MONITOR_HEALTH_LABELS.get(key, _title_case_words(key))


def present_auth_health(value: object) -> str:
    key = str(value or "").strip().lower()
    if not key or key == "—":
        return "—"
    return _AUTH_HEALTH_LABELS.get(key, _title_case_words(key))


def present_provider_health(value: object) -> str:
    key = str(value or "").strip().lower()
    if not key:
        return "Healthy"
    return _PROVIDER_HEALTH_LABELS.get(key, _title_case_words(key))


def present_systemic_alert(value: object) -> str:
    key = str(value or "").strip().lower()
    if not key or key == "—":
        return "None"
    return _SYSTEMIC_ALERT_LABELS.get(key, _title_case_words(key))


def present_run_status(value: object) -> str:
    key = str(value or "").strip().lower()
    if not key or key == "—":
        return "—"
    return _RUN_STATUS_LABELS.get(key, _title_case_words(key))


def present_run_trigger(value: object) -> str:
    key = str(value or "").strip().lower()
    if key == "manual":
        return "Manual"
    if key == "scheduled":
        return "Scheduled"
    return "—"


def budget_exhausted_skip_caption() -> str:
    return (
        "Today's monitoring budget has already been consumed. "
        "Remaining jobs will be checked after the daily budget resets."
    )


def present_latest_monitor_overview(run_info: dict[str, object] | None) -> str:
    """Operator-facing monitor status for the latest terminal run."""
    if not run_info:
        return "—"
    status = str(run_info.get("status") or "").strip().lower()
    if status == "skipped_budget_exhausted":
        return present_run_status(status)
    return present_monitor_health(run_info.get("monitor_health"))


def present_scheduler_state(value: object, *, operator_paused: bool = False) -> str:
    if operator_paused:
        return "Paused by operator"
    key = str(value or "").strip().lower()
    if not key:
        return "Unknown"
    return _SCHEDULER_STATE_LABELS.get(key, _title_case_words(key))


def present_reason_code(value: object) -> str:
    text = str(value or "").strip()
    if not text or text == "—":
        return "—"
    if ":" in text:
        prefix, detail = text.split(":", 1)
        prefix_label = _REASON_PREFIX_LABELS.get(prefix.strip().lower(), _title_case_words(prefix))
        detail_text = detail.replace("_", " ").strip()
        if detail_text:
            return f"{prefix_label}: {_title_case_words(detail_text)}"
        return prefix_label
    return _title_case_words(text)


def present_provider_health_detail(
    row: dict[str, object] | None,
) -> str:
    if not row:
        return "Healthy"
    health = present_provider_health(row.get("health"))
    reason = present_reason_code(row.get("reason"))
    if reason != "—":
        return f"{health} — {reason}"
    return health


def summarize_run_skip_issues(
    counts: dict[str, int],
    *,
    source: str,
) -> list[str]:
    """Plain-English lines for jobs skipped during the latest monitor run."""
    prefix = f"{source.lower()}_skipped_"
    label_map = (
        _LINKEDIN_RUN_ISSUE_LABELS if source.lower() == "linkedin" else _INSTAHYRE_RUN_ISSUE_LABELS
    )
    lines: list[str] = []
    for key, count in sorted(counts.items()):
        if count <= 0 or not key.startswith(prefix):
            continue
        reason = label_map.get(key, _title_case_words(key.replace(prefix, "")))
        job_word = "job" if count == 1 else "jobs"
        lines.append(f"{count} {job_word} not checked ({reason})")
    return lines


def present_next_retry(
    row: dict[str, object] | None,
    *,
    format_timestamp,
) -> tuple[bool, str]:
    """Return whether to show a next-retry row and the operator-facing label."""
    if not row:
        return False, ""
    health = str(row.get("health") or "ok").strip().lower()
    backoff_until = row.get("backoff_until")
    if backoff_until is not None:
        label = format_timestamp(backoff_until)
        return True, label if label != "—" else "Ready"
    if health not in ("", "ok"):
        return True, "Ready"
    return False, ""


def format_deferral_summary(counts: dict[str, int]) -> str:
    if not counts:
        return ""
    parts = [
        f"{_DEFERRAL_LABELS.get(key, _title_case_words(key))}: {value}"
        for key, value in sorted(counts.items())
    ]
    return "; ".join(parts)


BadgeTone = str  # ok | warn | error | neutral
BannerLevel = str  # green | orange | red


@dataclass(frozen=True)
class BannerResult:
    level: BannerLevel
    message: str
    details: tuple[str, ...] = ()


def render_status_badge(label: str, tone: BadgeTone) -> str:
    css_class = {
        "ok": "mon-badge-ok",
        "warn": "mon-badge-warn",
        "error": "mon-badge-error",
        "neutral": "mon-badge-neutral",
    }.get(tone, "mon-badge-neutral")
    return f'<span class="mon-status-badge {css_class}">{label}</span>'


def badge_tone_for_monitor_health(run_info: dict[str, object] | None) -> BadgeTone:
    if not run_info:
        return "neutral"
    status = str(run_info.get("status") or "").strip().lower()
    if status in ("failed", "interrupted"):
        return "error"
    if status == "skipped_budget_exhausted":
        return "warn"
    health = str(run_info.get("monitor_health") or "").strip().lower()
    if health == "degraded":
        return "warn"
    if health == "ok":
        return "ok"
    return "neutral"


def badge_tone_for_login_health(health: str) -> BadgeTone:
    key = (health or "").strip().lower()
    if key == "ok":
        return "ok"
    if key == "degraded":
        return "error"
    if key == "unknown":
        return "warn"
    return "neutral"


def _login_snapshots_for_overall(
    snapshots: dict[str, "ProviderMonitorSnapshot"],
) -> list["ProviderMonitorSnapshot"]:
    """Provider login rows that should affect overall login health."""
    applicable: list[ProviderMonitorSnapshot] = []
    for snap in snapshots.values():
        if snap.source == "instahyre" and not snap.login_applicable_this_run:
            continue
        applicable.append(snap)
    return applicable


def present_overall_login_health(
    snapshots: dict[str, "ProviderMonitorSnapshot"],
) -> tuple[str, BadgeTone]:
    """Worst-case login across providers — Connected only when all probes are ok."""
    applicable = _login_snapshots_for_overall(snapshots)
    if not applicable:
        return "—", "neutral"
    healths = [snap.login_health for snap in applicable]
    if all(h == "ok" for h in healths):
        return "Connected", "ok"
    if any(h == "degraded" for h in healths):
        return "Needs attention", "error"
    if any(h == "unknown" for h in healths):
        return "Not verified", "warn"
    return "Disconnected", "error"


def present_provider_login_health(snapshot: "ProviderMonitorSnapshot") -> tuple[str, BadgeTone]:
    if snapshot.source == "instahyre" and not snapshot.login_applicable_this_run:
        return "Not verified this run", "neutral"
    health = (snapshot.login_health or "").strip().lower()
    if health == "ok":
        return "Connected", "ok"
    if health == "degraded":
        return "Needs attention", "error"
    if health == "unknown":
        return "Not verified", "warn"
    return "Disconnected", "error"


def format_budget_usage(used: int, cap: int) -> str:
    return f"{max(0, used)} / {max(0, cap)}"


def _instahyre_login_needs_refresh(snapshot: "ProviderMonitorSnapshot") -> bool:
    if not snapshot.login_applicable_this_run:
        return False
    if (snapshot.login_health or "").strip().lower() != "degraded":
        return False
    reason = (snapshot.login_reason or "").strip().lower()
    return not reason.startswith("probe:")


def _parity_needs_review(value: object) -> bool:
    """True when parity_warning_summary contains real TD9 warnings (not the 'none' sentinel)."""
    text = str(value or "").strip()
    if not text:
        return False
    return text.lower() != "none"


def classify_status_banner(
    run_info: dict[str, object] | None,
    provider_snapshots: dict[str, "ProviderMonitorSnapshot"],
    *,
    protection_backoff_by_source: dict[str, bool] | None = None,
) -> BannerResult:
    """Classify operator status banner (red first, then orange, else green)."""
    if not run_info:
        return BannerResult(
            level="green",
            message="No completed monitor runs recorded yet.",
        )

    backoff = protection_backoff_by_source or {}
    status = str(run_info.get("status") or "").strip().lower()
    monitor_health = str(run_info.get("monitor_health") or "").strip().lower()
    systemic = str(run_info.get("systemic_alert") or "").strip().lower()

    linkedin = provider_snapshots.get("linkedin")
    instahyre = provider_snapshots.get("instahyre")

    if status in ("failed", "interrupted"):
        return BannerResult(
            level="red",
            message="Monitor run did not complete — operator intervention required.",
        )

    if linkedin and linkedin.login_health == "degraded":
        return BannerResult(
            level="red",
            message=(
                "LinkedIn login verification failed. "
                "Refresh the LinkedIn session before the next monitoring run."
            ),
        )
    if instahyre and _instahyre_login_needs_refresh(instahyre):
        return BannerResult(
            level="red",
            message=(
                "InstaHyre login verification failed. "
                "Refresh the InstaHyre session before the next monitoring run."
            ),
        )

    if backoff.get("linkedin") or backoff.get("instahyre"):
        return BannerResult(
            level="red",
            message="Provider protection pause is active — listing checks are deferred.",
        )

    if systemic == "provider_protection":
        return BannerResult(
            level="red",
            message="Provider protection was detected — review LinkedIn before the next run.",
        )

    details: list[str] = []
    if _parity_needs_review(run_info.get("parity_warning_summary")):
        details.append("Data parity review recommended for the latest run.")
    if status == "skipped_budget_exhausted":
        details.append(budget_exhausted_skip_caption())
    if monitor_health == "degraded":
        details.append("Latest run reported degraded monitor health.")
    if systemic == "high_check_failed_rate":
        details.append("Failure rate exceeded the alert threshold on the latest run.")
    for snap in provider_snapshots.values():
        if snap.budget_remaining <= 0 and snap.jobs_needing_attention > 0:
            label = "LinkedIn" if snap.source == "linkedin" else "InstaHyre"
            details.append(
                f"{label} daily budget is used but jobs still need attention."
            )

    if details:
        return BannerResult(
            level="orange",
            message="Review recommended before the next monitor run.",
            details=tuple(details),
        )

    return BannerResult(level="green", message="All clear — monitor health looks good.")
