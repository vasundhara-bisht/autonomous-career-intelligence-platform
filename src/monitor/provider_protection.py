"""Provider protection page detection for Scheduler B (OHM Phase 2)."""

from __future__ import annotations

from dataclasses import dataclass

from monitor.browser import PageFetchResult
from monitor.classifiers.text import extract_h1_text, html_to_text, normalize_text

# URL path/query fragments indicating provider enforcement or challenge flows.
_URL_PROTECTION_FRAGMENTS: tuple[str, ...] = (
    "checkpoint/challenge",
    "checkpoint",
    "unusual",
    "security",
)

# Enforcement-specific body markers (ordinary login walls are auth health, not protection).
_BODY_PROTECTION_MARKERS: tuple[str, ...] = (
    "unusual activity",
    "we noticed some unusual activity",
    "security verification",
    "temporarily restricted",
)

# Raw HTML structural markers (LinkedIn rehab / third-party verification).
_HTML_STRUCTURAL_MARKERS: tuple[str, ...] = (
    'id="rehab-challenge"',
    "id='rehab-challenge'",
    "rehab-challenge",
    "humanthirdpartyiframe",
    "protechts.net",
)


@dataclass(frozen=True)
class ProviderProtectionResult:
    """Outcome of provider protection evaluation for a fetched page."""

    is_protection: bool
    reason: str = ""
    protection_type: str = ""

    @classmethod
    def none(cls) -> ProviderProtectionResult:
        return cls(is_protection=False)

    @classmethod
    def detected(cls, *, reason: str, protection_type: str) -> ProviderProtectionResult:
        return cls(is_protection=True, reason=reason, protection_type=protection_type)


def _linkedin_job_page_has_live_shell(html: str) -> bool:
    from monitor.classifiers.linkedin import _detect_live_shell

    body_text = html_to_text(html)
    return _detect_live_shell(html, body_text)


def _url_protection_reason(low_url: str) -> str | None:
    if "checkpoint" in low_url or "challenge" in low_url:
        return "protection:checkpoint"
    if "unusual" in low_url or "security" in low_url:
        return "protection:unusual_activity"
    return None


def _body_protection_reason(body_text: str, *, h1_text: str) -> str | None:
    if "we noticed some unusual activity" in body_text or "unusual activity" in h1_text:
        return "protection:unusual_activity"
    if "security verification" in body_text or "temporarily restricted" in body_text:
        return "protection:unusual_activity"
    for marker in _BODY_PROTECTION_MARKERS:
        if marker in body_text:
            return "protection:unusual_activity"
    return None


def _protection_type_for_reason(reason: str) -> str:
    if reason == "protection:checkpoint":
        return "provider_challenge"
    return "provider_protection"


def detect_linkedin_protection(
    *,
    url: str,
    html: str,
    http_status: int | None = None,
    error: str | None = None,
) -> ProviderProtectionResult:
    """
    Detect LinkedIn provider protection / challenge pages.

    Protection is signaled when the page matches enforcement templates and lacks
    a live job shell — avoiding false positives on normal job detail pages.
    """
    del http_status  # reserved; fetch errors are infrastructure, not protection.
    if error:
        return ProviderProtectionResult.none()

    low_url = normalize_text(url)
    low_html = (html or "").lower()
    body_text = html_to_text(html)
    h1_text = extract_h1_text(html)

    url_reason = _url_protection_reason(low_url)
    has_structural_marker = any(marker in low_html for marker in _HTML_STRUCTURAL_MARKERS)
    body_reason = _body_protection_reason(body_text, h1_text=h1_text)

    if not url_reason and not has_structural_marker and not body_reason:
        return ProviderProtectionResult.none()

    if _linkedin_job_page_has_live_shell(html):
        return ProviderProtectionResult.none()

    if body_reason:
        return ProviderProtectionResult.detected(
            reason=body_reason,
            protection_type=_protection_type_for_reason(body_reason),
        )

    if has_structural_marker or url_reason == "protection:checkpoint":
        reason = url_reason or "protection:checkpoint"
        return ProviderProtectionResult.detected(
            reason=reason,
            protection_type=_protection_type_for_reason(reason),
        )

    if url_reason:
        return ProviderProtectionResult.detected(
            reason=url_reason,
            protection_type=_protection_type_for_reason(url_reason),
        )

    return ProviderProtectionResult.none()


def detect_provider_protection_from_fetch(
    fetch: PageFetchResult,
    *,
    source: str,
) -> ProviderProtectionResult:
    """Evaluate a page fetch for provider protection (LinkedIn only in Phase 2)."""
    src = (source or "").strip().lower()
    if src != "linkedin":
        return ProviderProtectionResult.none()
    return detect_linkedin_protection(
        url=fetch.url,
        html=fetch.html,
        http_status=fetch.http_status,
        error=fetch.error,
    )
