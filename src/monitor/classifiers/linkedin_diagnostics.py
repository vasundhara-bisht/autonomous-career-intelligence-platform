"""Temporary LinkedIn classifier diagnostics (read-only; does not affect outcomes)."""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field

from monitor.classifiers.linkedin import (
    _CLOSED_PHRASES,
    _FLAGSHIP3_APPLICANT_MARKERS,
    _FLAGSHIP3_RELATIVE_POSTED_RE,
    _LOGIN_MARKERS,
    _REMOVED_PHRASES,
    _DESCRIPTION_FRAGMENTS,
    _METADATA_FRAGMENTS,
    _TITLE_FRAGMENTS,
    _TOP_CARD_FRAGMENTS,
    _detect_apply_action,
    _detect_live_shell,
    _first_matching_phrase,
    _has_flagship3_shell_metadata,
    _has_job_title,
    _has_legacy_shell_structure,
    _has_shell_structure,
    _is_login_wall,
)
from monitor.classifiers.result import ListingClassification
from monitor.classifiers.text import (
    extract_h1_text,
    extract_main_content_text,
    html_contains_class_fragment,
    html_to_text,
)
from monitor.classifiers.url_validation import validate_linkedin_job_url

_MAIN_TAG_RE = re.compile(r"<main[^>]*>", re.IGNORECASE)
_H1_TAG_RE = re.compile(r"<h1[^>]*>.*?</h1>", re.IGNORECASE | re.DOTALL)
_SNIPPET_LIMIT = 500


def linkedin_classifier_debug_enabled() -> bool:
    return os.environ.get("LIFECYCLE_MONITOR_LINKEDIN_CLASSIFIER_DEBUG", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


@dataclass
class LinkedInClassifierDiagnosticReport:
    job_key_v2: str | None
    url: str
    http_status: int | None
    decision_path: list[str] = field(default_factory=list)
    outcome: ListingClassification | None = None
    signals: dict[str, object] = field(default_factory=dict)
    snippets: dict[str, str] = field(default_factory=dict)

    def format(self) -> str:
        lines = [
            "=== LINKEDIN CLASSIFIER DEBUG ===",
        ]
        if self.job_key_v2:
            lines.append(f"job_key_v2: {self.job_key_v2}")
        lines.append(f"url: {self.url}")
        lines.append(f"http_status: {self.http_status}")
        lines.append("")
        lines.append("--- Live shell signals ---")
        for key in (
            "has_job_title",
            "h1_title",
            "has_title_class_fragment",
            "has_legacy_shell_structure",
            "legacy_top_card_fragment",
            "legacy_description_fragment",
            "legacy_metadata_fragment",
            "main_tag_present",
            "middot_in_main",
            "flagship3_relative_posted_match",
            "flagship3_applicant_marker",
            "has_flagship3_shell_metadata",
            "has_shell_structure",
            "live_shell",
        ):
            if key in self.signals:
                lines.append(f"{key}: {self.signals[key]}")
        lines.append("")
        lines.append("--- Closure / removal signals ---")
        for key in (
            "removed_phrase",
            "closed_phrase",
            "has_apply_action",
        ):
            if key in self.signals:
                lines.append(f"{key}: {self.signals[key]}")
        lines.append("")
        lines.append("--- Auth signals ---")
        for key in (
            "is_login_wall",
            "login_wall_trigger",
        ):
            if key in self.signals:
                lines.append(f"{key}: {self.signals[key]}")
        lines.append("")
        lines.append("--- Decision path ---")
        for step in self.decision_path:
            lines.append(f"  {step}")
        lines.append("")
        lines.append("--- Outcome ---")
        if self.outcome is not None:
            lines.append(f"classification_succeeded: {self.outcome.classification_succeeded}")
            lines.append(f"listing_status: {self.outcome.listing_status}")
            lines.append(f"listing_status_reason: {self.outcome.listing_status_reason}")
        lines.append("")
        lines.append("--- Text / HTML snippets ---")
        for key, value in self.snippets.items():
            lines.append(f"{key}:")
            lines.append(value)
        lines.append("=== END LINKEDIN CLASSIFIER DEBUG ===")
        return "\n".join(lines)


def _snippet_around(text: str, needle: str, *, radius: int = 120) -> str:
    idx = text.find(needle)
    if idx < 0:
        return ""
    start = max(0, idx - radius)
    end = min(len(text), idx + len(needle) + radius)
    return text[start:end].strip()


def _truncate(text: str, limit: int = _SNIPPET_LIMIT) -> str:
    compact = " ".join((text or "").split())
    if len(compact) <= limit:
        return compact
    return f"{compact[:limit]}…"


def build_linkedin_classifier_diagnostic_report(
    *,
    url: str,
    html: str,
    http_status: int | None,
    classification: ListingClassification,
    job_key_v2: str | None = None,
) -> LinkedInClassifierDiagnosticReport:
    """Mirror classifier signal evaluation without changing the outcome."""
    report = LinkedInClassifierDiagnosticReport(
        job_key_v2=job_key_v2,
        url=url,
        http_status=http_status,
        outcome=classification,
    )

    body_text = html_to_text(html)
    main_text = extract_main_content_text(html)
    h1_title = extract_h1_text(html)

    legacy_top_card = html_contains_class_fragment(html, *_TOP_CARD_FRAGMENTS)
    legacy_description = html_contains_class_fragment(html, *_DESCRIPTION_FRAGMENTS)
    legacy_metadata = html_contains_class_fragment(html, *_METADATA_FRAGMENTS)
    has_legacy = _has_legacy_shell_structure(html)
    has_title = _has_job_title(html)
    has_title_class = html_contains_class_fragment(html, *_TITLE_FRAGMENTS)
    relative_match = _FLAGSHIP3_RELATIVE_POSTED_RE.search(main_text)
    applicant_marker = next(
        (marker for marker in _FLAGSHIP3_APPLICANT_MARKERS if marker in main_text),
        None,
    )
    has_flagship3 = _has_flagship3_shell_metadata(main_text)
    has_shell = _has_shell_structure(html)
    live_shell = _detect_live_shell(html, body_text)

    removed_phrase = _first_matching_phrase(body_text, _REMOVED_PHRASES)
    closed_phrase = _first_matching_phrase(body_text, _CLOSED_PHRASES)
    has_apply = _detect_apply_action(html, body_text)

    login_wall_trigger: str | None = None
    is_login_wall = _is_login_wall(
        url=url,
        html=html,
        body_text=body_text,
        live_shell=live_shell,
    )
    if is_login_wall:
        low_url = (url or "").lower()
        if "authwall" in low_url:
            login_wall_trigger = "url:authwall"
        elif "checkpoint/challenge" in low_url:
            login_wall_trigger = "url:checkpoint/challenge"
        elif h1_title in {"sign in", "join linkedin"}:
            login_wall_trigger = f"h1_title:{h1_title}"
        else:
            for marker in _LOGIN_MARKERS:
                if marker in main_text:
                    login_wall_trigger = f"main_text:{marker}"
                    break

    report.signals = {
        "has_job_title": has_title,
        "h1_title": h1_title or None,
        "has_title_class_fragment": has_title_class,
        "has_legacy_shell_structure": has_legacy,
        "legacy_top_card_fragment": legacy_top_card,
        "legacy_description_fragment": legacy_description,
        "legacy_metadata_fragment": legacy_metadata,
        "main_tag_present": bool(_MAIN_TAG_RE.search(html or "")),
        "middot_in_main": "·" in main_text,
        "flagship3_relative_posted_match": relative_match.group(0) if relative_match else None,
        "flagship3_applicant_marker": applicant_marker,
        "has_flagship3_shell_metadata": has_flagship3,
        "has_shell_structure": has_shell,
        "live_shell": live_shell,
        "removed_phrase": removed_phrase,
        "closed_phrase": closed_phrase,
        "has_apply_action": has_apply,
        "is_login_wall": is_login_wall,
        "login_wall_trigger": login_wall_trigger,
    }

    h1_html_match = _H1_TAG_RE.search(html or "")
    report.snippets = {
        "h1_html": _truncate(h1_html_match.group(0) if h1_html_match else "(no <h1> tag)"),
        "main_text": _truncate(main_text),
        "body_text_head": _truncate(body_text),
    }
    if closed_phrase:
        report.snippets["closed_phrase_context"] = _snippet_around(body_text, closed_phrase)
    if removed_phrase:
        report.snippets["removed_phrase_context"] = _snippet_around(body_text, removed_phrase)

    path = report.decision_path
    url_failure = validate_linkedin_job_url(url)
    if url_failure is not None:
        path.append("1. invalid_url -> check_failed")
        path.append(f"   reason={url_failure.listing_status_reason}")
        return report

    path.append("1. url_valid")
    path.append(f"2. live_shell={live_shell}")
    path.append(f"3. is_login_wall={is_login_wall}")
    if is_login_wall:
        path.append("4. login_wall -> check_failed:auth:login_wall")
        return report

    path.append("4. not_login_wall")
    path.append(f"5. removed_phrase={removed_phrase!r}")
    path.append(f"6. closed_phrase={closed_phrase!r}")
    path.append(f"7. http_status={http_status}")

    if http_status == 404:
        path.append("8. http_status==404 -> removed:http_404")
        return report

    if not live_shell:
        path.append("8. live_shell==false")
        if removed_phrase is not None:
            path.append("9. removed_phrase present -> removed:phrase:*")
            return report
        if closed_phrase is not None:
            path.append("9. closed_phrase on error shell -> removed:error_shell_with_closure")
            return report
        path.append("9. no closure/removal phrases -> check_failed:dom:no_live_shell")
        return report

    path.append("8. live_shell==true")
    if removed_phrase is not None:
        path.append("9. removed_phrase on live shell -> removed:phrase:*")
        return report
    if closed_phrase is not None:
        path.append("9. closed_phrase on live shell -> closed:phrase:*")
        return report
    if has_apply:
        path.append("9. apply signal present -> open:live_shell_apply")
        return report

    path.append("9. no closure/apply signals -> check_failed:dom:no_apply_signal")
    return report


def emit_linkedin_classifier_diagnostic_report(
    *,
    url: str,
    html: str,
    http_status: int | None,
    classification: ListingClassification,
    job_key_v2: str | None = None,
) -> None:
    report = build_linkedin_classifier_diagnostic_report(
        url=url,
        html=html,
        http_status=http_status,
        classification=classification,
        job_key_v2=job_key_v2,
    )
    print(report.format(), file=sys.stderr, flush=True)
