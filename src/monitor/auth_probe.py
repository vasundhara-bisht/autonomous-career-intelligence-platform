"""LinkedIn Authentication Health Probe for Scheduler B (TD6)."""

from __future__ import annotations

import os
from dataclasses import dataclass

from db.listing_status import AUTH_HEALTH_DEGRADED, AUTH_HEALTH_OK
from monitor.browser import PageFetchResult
from monitor.classifiers.text import html_to_text
from monitor.probe_infra import (
    PROBE_INFRASTRUCTURE_ERROR_PREFIXES,
    is_probe_infrastructure_error,
)

DEFAULT_LINKEDIN_AUTH_PROBE_URL = "https://www.linkedin.com/feed/"

_LOGIN_MARKERS = (
    "sign in",
    "join linkedin",
    "authwall",
    "checkpoint/challenge",
)


@dataclass(frozen=True)
class LinkedInAuthProbeResult:
    auth_health: str
    reason: str
    probe_url: str


def linkedin_auth_probe_url() -> str:
    raw = os.environ.get("LINKEDIN_MONITOR_AUTH_PROBE_URL", DEFAULT_LINKEDIN_AUTH_PROBE_URL)
    url = (raw or "").strip()
    return url or DEFAULT_LINKEDIN_AUTH_PROBE_URL


def evaluate_linkedin_auth_probe(
    *,
    probe_url: str,
    fetch: PageFetchResult,
) -> LinkedInAuthProbeResult:
    """Evaluate probe navigation result — session/auth only, not job availability."""
    if fetch.error:
        if is_probe_infrastructure_error(fetch.error):
            raise ValueError(
                "probe infrastructure error must be handled before auth evaluation: "
                f"{fetch.error}"
            )
        return LinkedInAuthProbeResult(
            auth_health=AUTH_HEALTH_DEGRADED,
            reason=fetch.error,
            probe_url=probe_url,
        )

    if fetch.http_status in {401, 403}:
        return LinkedInAuthProbeResult(
            auth_health=AUTH_HEALTH_DEGRADED,
            reason=f"auth:http_{fetch.http_status}",
            probe_url=probe_url,
        )

    body_text = html_to_text(fetch.html)
    if any(marker in body_text for marker in _LOGIN_MARKERS):
        return LinkedInAuthProbeResult(
            auth_health=AUTH_HEALTH_DEGRADED,
            reason="auth:login_wall",
            probe_url=probe_url,
        )

    return LinkedInAuthProbeResult(
        auth_health=AUTH_HEALTH_OK,
        reason="auth:ok",
        probe_url=probe_url,
    )


def run_linkedin_auth_probe(page_fetcher) -> LinkedInAuthProbeResult:
    """Navigate to the configured LinkedIn feed URL and evaluate session health."""
    probe_url = linkedin_auth_probe_url()
    fetch = page_fetcher(probe_url, "linkedin")
    if fetch.error and is_probe_infrastructure_error(fetch.error):
        raise ValueError(
            "probe infrastructure error must be handled before auth evaluation: "
            f"{fetch.error}"
        )
    return evaluate_linkedin_auth_probe(probe_url=probe_url, fetch=fetch)
