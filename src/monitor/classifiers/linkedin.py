"""LinkedIn /jobs/view/{id} lifecycle classifier (Product §4A)."""

from __future__ import annotations

import re

from db.listing_status import (
    LISTING_STATUS_CLOSED,
    LISTING_STATUS_OPEN,
    LISTING_STATUS_REMOVED,
)

from monitor.classifiers.result import ListingClassification
from monitor.classifiers.text import (
    extract_document_title_text,
    extract_h1_text,
    extract_main_content_text,
    html_contains_class_fragment,
    html_to_text,
    normalize_text,
)
from monitor.classifiers.url_validation import validate_linkedin_job_url

_LOGIN_MARKERS = (
    "sign in",
    "join linkedin",
    "authwall",
    "checkpoint/challenge",
)

_AUTH_TITLE_PHRASES = frozenset({"sign in", "join linkedin"})

_REMOVED_PHRASES: tuple[str, ...] = (
    "unable to load the page",
    "job id provided may not be valid",
    "job posting has been removed",
    "job unavailable",
    "job posting unavailable",
    "page not found",
)

_CLOSED_PHRASES: tuple[str, ...] = (
    "no longer accepting applications",
    "no longer accepting applicants",
    "we're no longer accepting applications",
    "we are no longer accepting applications",
    "not accepting applications",
)

_TOP_CARD_FRAGMENTS: tuple[str, ...] = (
    "job-details-jobs-unified-top-card",
    "jobs-unified-top-card",
    "primary-description-container",
    "jobs-details-top-card",
)

_DESCRIPTION_FRAGMENTS: tuple[str, ...] = (
    "jobs-description",
    "show-more-less-html",
    "jobs-box__html-content",
    "jobs-description-content__text",
)

_TITLE_FRAGMENTS: tuple[str, ...] = (
    "job-details-jobs-unified-top-card__job-title",
    "jobs-unified-top-card__job-title",
    "jobs-details-top-card__job-title",
)

_METADATA_FRAGMENTS: tuple[str, ...] = (
    "primary-description-container",
    "jobs-unified-top-card__subtitle",
    "job-details-jobs-unified-top-card__primary-description",
)

# Mirror scraper.linkedin _LI_RELATIVE_POSTED_RE / flagship3 metadata fallback.
_FLAGSHIP3_RELATIVE_POSTED_RE = re.compile(
    r"\d+\s+(hour|day|week|month)s?\s+ago",
    re.IGNORECASE,
)
_FLAGSHIP3_APPLICANT_MARKERS: tuple[str, ...] = (
    "applicant",
    "clicked apply",
    "people clicked",
)


def _first_matching_phrase(body_text: str, phrases: tuple[str, ...]) -> str | None:
    for phrase in phrases:
        if phrase in body_text:
            return phrase
    return None


def _job_title_from_page_title(page_title: str) -> str | None:
    """Mirror scraper.linkedin _li_title_company_from_page_title job-title segment."""
    parts = [part.strip() for part in (page_title or "").split("|")]
    if len(parts) < 3 or "linkedin" not in parts[-1].lower():
        return None
    title = normalize_text(parts[0])
    if not title or title in _AUTH_TITLE_PHRASES:
        return None
    return title


def _has_job_title(html: str) -> bool:
    h1_title = extract_h1_text(html)
    if h1_title and h1_title not in _AUTH_TITLE_PHRASES:
        return True
    if html_contains_class_fragment(html, *_TITLE_FRAGMENTS):
        return True
    return _job_title_from_page_title(extract_document_title_text(html)) is not None


def _has_legacy_shell_structure(html: str) -> bool:
    return (
        html_contains_class_fragment(html, *_TOP_CARD_FRAGMENTS)
        or html_contains_class_fragment(html, *_DESCRIPTION_FRAGMENTS)
        or html_contains_class_fragment(html, *_METADATA_FRAGMENTS)
    )


def _has_flagship3_shell_metadata(main_text: str) -> bool:
    """
    Flagship3 job view shell: <main> metadata line with middot-separated fields.

    Matches acquisition scraper _li_extract_time_posted_flagship3_fallback heuristics.
    Requires a title signal separately (closure phrase alone is not sufficient).
    """
    if "·" not in main_text:
        return False
    if _FLAGSHIP3_RELATIVE_POSTED_RE.search(main_text):
        return True
    return any(marker in main_text for marker in _FLAGSHIP3_APPLICANT_MARKERS)


def _has_shell_structure(html: str) -> bool:
    if _has_legacy_shell_structure(html):
        return True
    if _has_job_title(html):
        return _has_flagship3_shell_metadata(extract_main_content_text(html))
    return False


def _detect_live_shell(html: str, body_text: str) -> bool:
    """Product §4A: title visible AND (legacy shell OR flagship3 metadata shell)."""
    del body_text  # closure phrase alone must not imply shell.
    return _has_job_title(html) and _has_shell_structure(html)


def _is_login_wall(
    *,
    url: str,
    html: str,
    body_text: str,
    live_shell: bool,
) -> bool:
    low_url = normalize_text(url)
    if "authwall" in low_url or "checkpoint/challenge" in low_url:
        return True

    if live_shell:
        return False

    h1_title = extract_h1_text(html)
    if h1_title in _AUTH_TITLE_PHRASES:
        return True

    main_text = extract_main_content_text(html)
    return any(marker in main_text for marker in _LOGIN_MARKERS)


def _detect_apply_action(html: str, body_text: str) -> bool:
    low_html = (html or "").lower()
    if any(
        marker in low_html
        for marker in (
            "jobs-apply-button",
            "jobs-s-apply",
            'aria-label="apply',
            "aria-label='apply",
        )
    ):
        return True
    return any(
        phrase in body_text
        for phrase in ("easy apply", "apply now", "apply on company website")
    )


_APPLIED_STATUS_CLASS = "jobs-s-apply__application-status-text"
_APPLIED_STATUS_TEXT_RE = re.compile(
    rf'class="[^"]*{_APPLIED_STATUS_CLASS}[^"]*"[^>]*>([^<]+)<',
    re.IGNORECASE,
)
_FLAGSHIP3_APPLICATION_STATUS_HEADING = "application status"
_FLAGSHIP3_APPLICATION_SUBMITTED_PHRASE = "application submitted"


def _detect_legacy_linkedin_applied(html: str) -> bool:
    match = _APPLIED_STATUS_TEXT_RE.search(html or "")
    if not match:
        return False
    return "applied" in match.group(1).lower()


def _detect_flagship3_linkedin_applied(html: str) -> bool:
    text = normalize_text(html_to_text(html or ""))
    if _FLAGSHIP3_APPLICATION_STATUS_HEADING not in text:
        return False
    return _FLAGSHIP3_APPLICATION_SUBMITTED_PHRASE in text


def detect_linkedin_user_applied(html: str) -> bool:
    """
    User-applied signal on a LinkedIn job detail page.

    Mirrors scraper.linkedin applied-status detection plus flagship3
    \"Application submitted\" markup.
    """
    if not html:
        return False
    return _detect_legacy_linkedin_applied(html) or _detect_flagship3_linkedin_applied(html)


def classify_linkedin_page(
    *,
    url: str,
    html: str,
    http_status: int | None = None,
) -> ListingClassification:
    """
    Classify a loaded LinkedIn job detail page.

    Priority: removed > closed > check_failed > open (Product §4A).
    """
    url_failure = validate_linkedin_job_url(url)
    if url_failure is not None:
        return url_failure

    body_text = html_to_text(html)
    live_shell = _detect_live_shell(html, body_text)

    if _is_login_wall(url=url, html=html, body_text=body_text, live_shell=live_shell):
        return ListingClassification.check_failed("auth:login_wall")

    removed_phrase = _first_matching_phrase(body_text, _REMOVED_PHRASES)
    closed_phrase = _first_matching_phrase(body_text, _CLOSED_PHRASES)

    if http_status == 404:
        return ListingClassification.succeeded(
            LISTING_STATUS_REMOVED,
            "removed:http_404",
        )

    if not live_shell:
        if removed_phrase is not None:
            return ListingClassification.succeeded(
                LISTING_STATUS_REMOVED,
                f"removed:phrase:{removed_phrase.replace(' ', '_')}",
            )
        if closed_phrase is not None:
            # Error shell + closure phrase → removed (no usable posting).
            return ListingClassification.succeeded(
                LISTING_STATUS_REMOVED,
                "removed:error_shell_with_closure",
            )
        return ListingClassification.check_failed("dom:no_live_shell")

    if removed_phrase is not None:
        # Live shell should not coexist with tier-1 copy; treat as removed if present.
        return ListingClassification.succeeded(
            LISTING_STATUS_REMOVED,
            f"removed:phrase:{removed_phrase.replace(' ', '_')}",
        )

    if closed_phrase is not None:
        return ListingClassification.succeeded(
            LISTING_STATUS_CLOSED,
            f"closed:phrase:{closed_phrase.replace(' ', '_')}",
        )

    if _detect_apply_action(html, body_text):
        return ListingClassification.succeeded(LISTING_STATUS_OPEN, "open:live_shell_apply")

    return ListingClassification.check_failed("dom:no_apply_signal")
