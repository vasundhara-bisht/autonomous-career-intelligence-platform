"""Instahyre job detail lifecycle classifier (TD7 §4.5)."""

from __future__ import annotations

import re

from db.listing_status import (
    LISTING_STATUS_CLOSED,
    LISTING_STATUS_OPEN,
    LISTING_STATUS_REMOVED,
)
from scraper.instahyre import _DETAIL_REJECT_PHRASES

from monitor.classifiers.result import ListingClassification
from monitor.classifiers.text import (
    extract_h1_text,
    html_contains_class_fragment,
    html_to_text,
    normalize_text,
)
from monitor.classifiers.url_validation import validate_instahyre_job_url

_INSTAHYRE_REMOVED_PHRASES: tuple[str, ...] = (
    "page not found",
    "404",
)

_INSTAHYRE_CLOSED_PHRASES: tuple[str, ...] = (
    "no longer accepting applications",
)

_INSTAHYRE_LOGIN_MARKERS: tuple[str, ...] = (
    "log in to instahyre",
    "sign in to instahyre",
    "login to instahyre",
    "please log in",
    "please sign in",
)

_COMPANY_FRAGMENTS: tuple[str, ...] = (
    "company-name",
    "companyname",
    "employer",
)

_DESCRIPTION_FRAGMENTS: tuple[str, ...] = (
    "job-description",
    "jobdescription",
)


def _phrase_buckets() -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Map scraper reject phrases into removed vs closed buckets."""
    removed: list[str] = []
    closed: list[str] = []
    for phrase in _DETAIL_REJECT_PHRASES:
        low = phrase.lower()
        if low in _INSTAHYRE_REMOVED_PHRASES:
            removed.append(low)
        elif low in _INSTAHYRE_CLOSED_PHRASES:
            closed.append(low)
    return tuple(removed), tuple(closed)


_REMOVED_PHRASES, _CLOSED_PHRASES = _phrase_buckets()


def _first_matching_phrase(body_text: str, phrases: tuple[str, ...]) -> str | None:
    for phrase in phrases:
        if phrase in body_text:
            return phrase
    return None


def _is_auth_failure(*, url: str, body_text: str) -> bool:
    low_url = (url or "").lower()
    if "/login" in low_url:
        return True
    if "sign" in low_url and "/job-" not in low_url:
        return True
    return any(marker in body_text for marker in _INSTAHYRE_LOGIN_MARKERS)


def _title_is_valid(html: str, body_text: str) -> bool:
    title = extract_h1_text(html)
    if not title:
        return False
    return _first_matching_phrase(title, _REMOVED_PHRASES + _CLOSED_PHRASES) is None


def _detect_live_shell(html: str, body_text: str) -> bool:
    if not _title_is_valid(html, body_text):
        return False
    has_company = html_contains_class_fragment(html, *_COMPANY_FRAGMENTS) or bool(
        re.search(r"<h2[^>]*>.*?</h2>", html or "", re.IGNORECASE | re.DOTALL)
    )
    has_description = html_contains_class_fragment(html, *_DESCRIPTION_FRAGMENTS)
    return has_company or has_description


def classify_instahyre_page(
    *,
    url: str,
    html: str,
    http_status: int | None = None,
) -> ListingClassification:
    """
    Classify a loaded Instahyre job detail page.

    Priority: removed > closed > check_failed > open (TD7 §4.5).
    """
    url_failure = validate_instahyre_job_url(url)
    if url_failure is not None:
        return url_failure

    body_text = html_to_text(html)

    if _is_auth_failure(url=url, body_text=body_text):
        return ListingClassification.check_failed("auth:session_invalid")

    removed_phrase = _first_matching_phrase(body_text, _REMOVED_PHRASES)
    closed_phrase = _first_matching_phrase(body_text, _CLOSED_PHRASES)

    if http_status == 404:
        return ListingClassification.succeeded(
            LISTING_STATUS_REMOVED,
            "removed:http_404",
        )

    if removed_phrase is not None:
        return ListingClassification.succeeded(
            LISTING_STATUS_REMOVED,
            f"removed:phrase:{removed_phrase.replace(' ', '_')}",
        )

    if closed_phrase is not None:
        return ListingClassification.succeeded(
            LISTING_STATUS_CLOSED,
            f"closed:phrase:{closed_phrase.replace(' ', '_')}",
        )

    if _detect_live_shell(html, body_text):
        return ListingClassification.succeeded(LISTING_STATUS_OPEN, "open:live_detail_shell")

    return ListingClassification.check_failed("dom:no_detail_shell")
