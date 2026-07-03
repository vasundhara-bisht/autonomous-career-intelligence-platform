"""InstaHyre auth probe for lifecycle monitor runs."""

from __future__ import annotations

import os
from dataclasses import dataclass

from db.listing_status import AUTH_HEALTH_DEGRADED, AUTH_HEALTH_OK
from monitor.browser import PageFetchResult
from monitor.instahyre_session import evaluate_instahyre_session_fetch
from monitor.probe_infra import is_probe_infrastructure_error

DEFAULT_INSTAHYRE_AUTH_PROBE_URL = "https://www.instahyre.com/candidate/profile/"
INSTAHYRE_AUTH_OK_MONITOR_RECONCILIATION = "auth:ok_monitor_reconciliation"


@dataclass(frozen=True)
class InstaHyreAuthProbeResult:
    auth_health: str
    reason: str
    probe_url: str


def instahyre_auth_probe_url() -> str:
    return os.environ.get(
        "INSTAHYRE_MONITOR_AUTH_PROBE_URL",
        DEFAULT_INSTAHYRE_AUTH_PROBE_URL,
    ).strip()


def evaluate_instahyre_auth_probe(
    *,
    probe_url: str,
    fetch: PageFetchResult,
) -> InstaHyreAuthProbeResult:
    """Evaluate probe navigation result — session/auth only, not job availability."""
    if fetch.error:
        if is_probe_infrastructure_error(fetch.error):
            raise ValueError(
                "probe infrastructure error must be handled before auth evaluation: "
                f"{fetch.error}"
            )
        return InstaHyreAuthProbeResult(
            auth_health=AUTH_HEALTH_DEGRADED,
            reason=fetch.error,
            probe_url=probe_url,
        )

    auth_health, reason = evaluate_instahyre_session_fetch(
        final_url=fetch.url,
        status_code=fetch.http_status,
        html=fetch.html,
    )
    return InstaHyreAuthProbeResult(
        auth_health=auth_health,
        reason=reason,
        probe_url=probe_url,
    )


def run_instahyre_auth_probe(page_fetcher) -> InstaHyreAuthProbeResult:
    """Navigate to the configured InstaHyre profile URL and evaluate session health."""
    probe_url = instahyre_auth_probe_url()
    fetch = page_fetcher(probe_url, "instahyre")
    if fetch.error and is_probe_infrastructure_error(fetch.error):
        raise ValueError(
            "probe infrastructure error must be handled before auth evaluation: "
            f"{fetch.error}"
        )
    return evaluate_instahyre_auth_probe(probe_url=probe_url, fetch=fetch)


def reconcile_instahyre_auth_health(
    *,
    instahyre_auth_health: str | None,
    instahyre_auth_probe_reason: str | None,
    job_results: list[object],
) -> tuple[str | None, str | None]:
    """Override a false-negative probe when monitoring proves the session is valid."""
    if instahyre_auth_health != AUTH_HEALTH_DEGRADED:
        return instahyre_auth_health, instahyre_auth_probe_reason

    has_successful_check = False
    for check in job_results:
        source = str(getattr(check, "source", "") or "").strip().lower()
        if source != "instahyre":
            continue
        if bool(getattr(check, "skipped", False)):
            continue
        reason = str(getattr(check, "outcome_reason", "") or "")
        if not reason.startswith("auth:"):
            has_successful_check = True
            break

    if has_successful_check:
        return AUTH_HEALTH_OK, INSTAHYRE_AUTH_OK_MONITOR_RECONCILIATION
    return instahyre_auth_health, instahyre_auth_probe_reason
