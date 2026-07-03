"""HTML and text helpers for offline classifier evaluation."""

from __future__ import annotations

import re

_SCRIPT_STYLE_RE = re.compile(
    r"<(script|style|noscript)[^>]*>.*?</\1>",
    re.IGNORECASE | re.DOTALL,
)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def normalize_text(text: str) -> str:
    return _WS_RE.sub(" ", (text or "").strip().lower())


def html_to_text(html: str) -> str:
    """Best-effort visible text extraction for fixture-based classification."""
    cleaned = _SCRIPT_STYLE_RE.sub(" ", html or "")
    without_tags = _TAG_RE.sub(" ", cleaned)
    return normalize_text(without_tags)


def extract_h1_text(html: str) -> str:
    match = re.search(r"<h1[^>]*>(.*?)</h1>", html or "", re.IGNORECASE | re.DOTALL)
    if not match:
        return ""
    return normalize_text(html_to_text(match.group(1)))


def extract_document_title_text(html: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", html or "", re.IGNORECASE | re.DOTALL)
    if not match:
        return ""
    return normalize_text(html_to_text(match.group(1)))


def html_contains_class_fragment(html: str, *fragments: str) -> bool:
    low = (html or "").lower()
    return any(fragment.lower() in low for fragment in fragments)


_MAIN_CONTENT_RE = re.compile(
    r"<main[^>]*>(.*?)</main>",
    re.IGNORECASE | re.DOTALL,
)


def extract_main_content_text(html: str) -> str:
    """Prefer <main> landmark text for auth/shell heuristics; fallback to full page."""
    match = _MAIN_CONTENT_RE.search(html or "")
    if match:
        return html_to_text(match.group(1))
    return html_to_text(html)
