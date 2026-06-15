"""Reusable display helpers for truncated text and rationale popovers."""

from __future__ import annotations

import re
from typing import Protocol

import streamlit as st


class _RationaleSource(Protocol):
    rationale: str
    full_rationale: str


def truncate_for_display(text: object, max_len: int) -> tuple[str, bool]:
    """Return display string and whether the source was truncated."""
    raw = str(text or "").strip()
    if max_len <= 0 or len(raw) <= max_len:
        return raw, False
    return raw[: max_len - 1].rstrip() + "…", True


def is_valid_job_url(url: object) -> bool:
    """True when url is a non-empty http(s) posting link."""
    text = str(url or "").strip()
    if not text:
        return False
    lowered = text.lower()
    return lowered.startswith("http://") or lowered.startswith("https://")


def format_action_rationale(action: _RationaleSource) -> tuple[str, str]:
    """Map a RecommendedAction to (compact display, full rationale)."""
    full = str(action.full_rationale or action.rationale or "").strip()
    display = str(action.rationale or "").strip()
    return display, full


_RATIONALE_FIELD_SPLIT = re.compile(
    r"\s+(?=(?:AI score\b|Discovered\b|Stage:|In\b|Not yet applied\b|AI reason:))"
)


def _format_rationale_line(line: str) -> str:
    text = str(line or "").strip()
    if not text:
        return ""

    if text.startswith("AI score "):
        return f"**AI score:** {text[len('AI score '):].strip()}"
    if text.startswith("Discovered "):
        return f"**Discovered:** {text[len('Discovered '):].strip()}"
    if text.startswith("Stage:"):
        return f"**Stage:** {text[len('Stage:'):].strip()}"
    if text.startswith("In "):
        return f"**In stage:** {text[len('In '):].strip()}"
    if text.startswith("Not yet applied"):
        return "**Status:** Not yet applied"
    if text.startswith("AI reason:"):
        return f"**AI reason:** {text[len('AI reason:'):].strip()}"
    return text


def format_rationale_for_popover(full_text: str) -> str:
    """Render rationale as readable markdown lines for the Why? popover."""
    raw = str(full_text or "").strip()
    if not raw:
        return ""

    if "\n" in raw:
        lines = [line.strip() for line in raw.splitlines() if line.strip()]
    else:
        lines = [part.strip() for part in _RATIONALE_FIELD_SPLIT.split(raw) if part.strip()]

    formatted = [_format_rationale_line(line) for line in lines]
    return "\n\n".join(part for part in formatted if part)


def render_why_text_action(full_text: str, *, key: str) -> None:
    """Secondary text-styled Why? popover; rationale hidden until opened."""
    formatted = format_rationale_for_popover(full_text)
    if not formatted:
        return

    if hasattr(st, "popover"):
        with st.popover("Why?", help="Why this job is recommended", key=key):
            st.markdown(formatted)
    else:
        with st.expander("Why?", expanded=False):
            st.markdown(formatted)


def render_why_popover(full_text: str, *, key: str) -> None:
    """Backward-compatible alias for render_why_text_action."""
    render_why_text_action(full_text, key=key)
