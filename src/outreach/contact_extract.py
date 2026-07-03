"""Deterministic contact extraction from hiring signal post text."""

from __future__ import annotations

import re

_EMAIL_PATTERN = re.compile(
    r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"
)
_MAX_EMAILS = 3
_OBFUSCATION_REPLACEMENTS = (
    (re.compile(r"\s*\[at\]\s*", re.IGNORECASE), "@"),
    (re.compile(r"\s*\(at\)\s*", re.IGNORECASE), "@"),
    (re.compile(r"\s*\[dot\]\s*", re.IGNORECASE), "."),
    (re.compile(r"\s*\(dot\)\s*", re.IGNORECASE), "."),
    (re.compile(r"\b([A-Za-z0-9._%+\-]+)\s+at\s+([A-Za-z0-9.\-]+)\s+dot\s+([A-Za-z]{2,})\b", re.IGNORECASE), r"\1@\2.\3"),
)


def _deobfuscate_email_text(text: str) -> str:
    normalized = str(text or "")
    for pattern, replacement in _OBFUSCATION_REPLACEMENTS:
        normalized = pattern.sub(replacement, normalized)
    return normalized


def extract_emails_from_text(text: str) -> list[str]:
    """Return up to three unique emails found in post text (best-effort de-obfuscation)."""
    candidates = _EMAIL_PATTERN.findall(_deobfuscate_email_text(text))
    seen: set[str] = set()
    emails: list[str] = []
    for raw in candidates:
        email = raw.strip().lower()
        if not email or email in seen:
            continue
        seen.add(email)
        emails.append(email)
        if len(emails) >= _MAX_EMAILS:
            break
    return emails


def merge_application_emails(
    *,
    detected_emails: list[str],
    ai_emails: list[str] | None,
) -> list[str]:
    """Union regex-detected and AI emails, regex order first."""
    merged: list[str] = []
    seen: set[str] = set()
    for source in (detected_emails, list(ai_emails or [])):
        for raw in source:
            email = str(raw or "").strip().lower()
            if not email or email in seen:
                continue
            seen.add(email)
            merged.append(email)
            if len(merged) >= _MAX_EMAILS:
                return merged
    return merged


def format_application_contact_section(emails: list[str]) -> str:
    if not emails:
        return ""
    lines = ["Application Contact:"]
    lines.extend(emails)
    return "\n".join(lines)
