"""Dashboard UI for job-centric Recommended Actions (Phase 3A / 3A.2 command center)."""

from __future__ import annotations

import hashlib
import html
import inspect

import pandas as pd
import streamlit as st

from db.read.engine import dashboard_write_enabled
from db.services.dashboard_write import mark_job_applied
from display_text import is_valid_job_url, render_why_text_action
from ui_help import help_icon_html, inject_dashboard_help_css
from recommended_actions import RecommendedAction, compute_recommended_actions
from recommended_actions_config import (
    APPLY_ACTION_QUEUES,
    APPLY_TODAY_LABEL,
    APPLY_THIS_WEEK_LABEL,
    DISPLAY_CAP_BY_QUEUE,
    HIGH_CONFIDENCE_LABEL,
    NEEDS_REVIEW_LABEL,
    QUEUE_APPLY_THIS_WEEK,
    QUEUE_APPLY_TODAY,
    QUEUE_HIGH_CONFIDENCE,
    QUEUE_LOAD_MORE_INCREMENT,
    QUEUE_NEEDS_REVIEW,
    RECOMMENDED_ACTIONS_TITLE,
    compute_queue_panel_height_px,
)

_SESSION_VISIBLE_HIGH_CONFIDENCE = "rec_visible_high_confidence"
_SESSION_VISIBLE_APPLY_TODAY = "rec_visible_apply_today"
_SESSION_VISIBLE_APPLY_THIS_WEEK = "rec_visible_apply_this_week"
_SESSION_VISIBLE_NEEDS_REVIEW = "rec_visible_needs_review"

_VISIBLE_STATE_KEYS = {
    QUEUE_HIGH_CONFIDENCE: _SESSION_VISIBLE_HIGH_CONFIDENCE,
    QUEUE_APPLY_TODAY: _SESSION_VISIBLE_APPLY_TODAY,
    QUEUE_APPLY_THIS_WEEK: _SESSION_VISIBLE_APPLY_THIS_WEEK,
    QUEUE_NEEDS_REVIEW: _SESSION_VISIBLE_NEEDS_REVIEW,
}

_NEEDS_REVIEW_HELP_LINES = (
    "Jobs that have been in your list for 14+ days.",
    "Review and either Apply, Save intentionally, or Reject.",
)

_PANEL_CSS = """
<style>
.rec-queue-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.35rem;
}
.rec-queue-header-text {
    flex: 1;
    min-width: 0;
}
.rec-queue-header.high-confidence {
    border-left: 5px solid rgba(25, 118, 210, 0.95);
    background: rgba(25, 118, 210, 0.07);
    border-radius: 0.3rem;
    padding: 0.45rem 0.6rem 0.45rem 0.6rem;
    margin-top: 0.1rem;
    margin-bottom: 0.7rem;
    font-size: 1.2rem;
    font-weight: 800;
    line-height: 1.25;
    letter-spacing: 0.01em;
}
.rec-queue-header.apply-today {
    border-left: 5px solid rgba(46, 125, 50, 0.95);
    background: rgba(46, 125, 50, 0.07);
    border-radius: 0.3rem;
    padding: 0.45rem 0.6rem 0.45rem 0.6rem;
    margin-top: 0.1rem;
    margin-bottom: 0.7rem;
    font-size: 1.2rem;
    font-weight: 800;
    line-height: 1.25;
    letter-spacing: 0.01em;
}
.rec-queue-header.apply-this-week {
    border-left: 5px solid rgba(0, 131, 143, 0.95);
    background: rgba(0, 131, 143, 0.07);
    border-radius: 0.3rem;
    padding: 0.45rem 0.6rem 0.45rem 0.6rem;
    margin-top: 0.1rem;
    margin-bottom: 0.7rem;
    font-size: 1.2rem;
    font-weight: 800;
    line-height: 1.25;
    letter-spacing: 0.01em;
}
.rec-queue-header.needs-review {
    border-left: 5px solid rgba(200, 145, 0, 0.98);
    background: rgba(200, 145, 0, 0.08);
    border-radius: 0.3rem;
    padding: 0.45rem 0.6rem 0.45rem 0.6rem;
    margin-top: 0.1rem;
    margin-bottom: 0.7rem;
    font-size: 1.2rem;
    font-weight: 800;
    line-height: 1.25;
    letter-spacing: 0.01em;
}
.rec-queue-header.high-confidence span.count {
    color: rgb(13, 71, 161);
}
.rec-queue-header.apply-today span.count {
    color: rgb(27, 94, 32);
}
.rec-queue-header.apply-this-week span.count {
    color: rgb(0, 96, 100);
}
.rec-queue-header.needs-review span.count {
    color: rgb(130, 90, 0);
}
div[data-testid="element-container"]:has([data-testid="stVerticalBlockBorderWrapper"]):has(+ div[data-testid="element-container"]:has(.rec-queue-footer-row)) {
    margin-bottom: -0.65rem !important;
    padding-bottom: 0 !important;
}
div[data-testid="element-container"]:has([data-testid="stVerticalBlockBorderWrapper"]):has(+ div[data-testid="element-container"]:has(.rec-queue-footer-row)) [data-testid="stVerticalBlockBorderWrapper"] {
    margin-bottom: 0 !important;
}
div[data-testid="element-container"]:has([data-testid="stVerticalBlockBorderWrapper"]) + div[data-testid="element-container"]:has(.rec-queue-footer-row) {
    margin-top: -1.55rem !important;
    margin-bottom: 0 !important;
    padding: 0 !important;
    height: 0 !important;
    min-height: 0 !important;
    overflow: visible !important;
}
div[data-testid="element-container"]:has(.rec-queue-footer-row) + div[data-testid="stHorizontalBlock"] {
    align-items: center !important;
    margin-top: -0.55rem !important;
    margin-bottom: 0.35rem !important;
    padding-top: 0 !important;
    padding-bottom: 0 !important;
}
div[data-testid="element-container"]:has(.rec-queue-footer-row) + div[data-testid="stHorizontalBlock"] [data-testid="stCaptionContainer"],
div[data-testid="element-container"]:has(.rec-queue-footer-row) + div[data-testid="stHorizontalBlock"] [data-testid="stCaptionContainer"] p {
    margin-top: 0 !important;
    margin-bottom: 0 !important;
    padding-top: 0 !important;
    padding-bottom: 0 !important;
}
div[data-testid="element-container"]:has(.rec-queue-footer-row) + div[data-testid="stHorizontalBlock"] [data-testid="column"]:last-child {
    display: flex !important;
    justify-content: flex-end !important;
}
div[data-testid="element-container"]:has(.rec-queue-footer-row) + div[data-testid="stHorizontalBlock"] [data-testid="column"]:last-child button {
    width: auto !important;
    min-width: 6.5rem;
    margin-top: 0 !important;
    margin-bottom: 0 !important;
}
div[data-testid="element-container"]:has(.rec-queue-panel-end) {
    margin-top: 0 !important;
    margin-bottom: 2.35rem !important;
    padding: 0 !important;
    height: 0 !important;
    min-height: 0 !important;
    overflow: hidden !important;
}
div[data-testid="element-container"]:has(.rec-action-row-start) + div[data-testid="stHorizontalBlock"] {
    align-items: center !important;
    margin-top: 0 !important;
    margin-bottom: 0 !important;
    gap: 0.4rem !important;
}
div[data-testid="element-container"]:has(.rec-action-row-start) + div[data-testid="stHorizontalBlock"] > div[data-testid="column"] {
    display: flex !important;
    align-items: center !important;
    align-self: center !important;
    justify-content: center !important;
    min-height: 2.5rem !important;
}
div[data-testid="element-container"]:has(.rec-action-row-start) + div[data-testid="stHorizontalBlock"] > div[data-testid="column"] > div[data-testid="stVerticalBlock"] {
    width: 100% !important;
    justify-content: center !important;
}
div[data-testid="element-container"]:has(.rec-action-row-start) + div[data-testid="stHorizontalBlock"] [data-testid="element-container"] {
    margin: 0 !important;
    padding: 0 !important;
    width: 100% !important;
}
div[data-testid="element-container"]:has(.rec-action-row-start) + div[data-testid="stHorizontalBlock"] [data-testid="stLinkButton"],
div[data-testid="element-container"]:has(.rec-action-row-start) + div[data-testid="stHorizontalBlock"] [data-testid="stButton"],
div[data-testid="element-container"]:has(.rec-action-row-start) + div[data-testid="stHorizontalBlock"] div[data-testid="stPopover"] {
    width: 100% !important;
}
div[data-testid="element-container"]:has(.rec-action-row-start) + div[data-testid="stHorizontalBlock"] [data-testid="stLinkButton"] a,
div[data-testid="element-container"]:has(.rec-action-row-start) + div[data-testid="stHorizontalBlock"] button,
div[data-testid="element-container"]:has(.rec-action-row-start) + div[data-testid="stHorizontalBlock"] div[data-testid="stPopover"] > button {
    height: 2.5rem !important;
    min-height: 2.5rem !important;
    max-height: 2.5rem !important;
    margin: 0 !important;
    box-sizing: border-box !important;
    display: inline-flex !important;
    align-items: center !important;
    justify-content: center !important;
    white-space: nowrap !important;
    line-height: 1 !important;
}
div[data-testid="element-container"]:has(.rec-action-row-start) + div[data-testid="stHorizontalBlock"] > div[data-testid="column"]:nth-child(2) button {
    background-color: transparent !important;
    border: none !important;
    box-shadow: none !important;
    color: #6b7280 !important;
    font-size: 0.78rem !important;
    font-weight: 400 !important;
    padding: 0 0.15rem !important;
}
div[data-testid="element-container"]:has(.rec-action-row-start) + div[data-testid="stHorizontalBlock"] > div[data-testid="column"]:nth-child(2) button:hover:not(:disabled) {
    text-decoration: underline !important;
    color: #4b5563 !important;
    background-color: transparent !important;
}
div[data-testid="element-container"]:has(.rec-action-row-start) + div[data-testid="stHorizontalBlock"] > div[data-testid="column"]:nth-child(3) div[data-testid="stPopover"] > button {
    background-color: transparent !important;
    border: none !important;
    box-shadow: none !important;
    color: #6b7280 !important;
    font-size: 0.78rem !important;
    font-weight: 400 !important;
    padding: 0 0.15rem !important;
}
div[data-testid="element-container"]:has(.rec-action-row-start) + div[data-testid="stHorizontalBlock"] > div[data-testid="column"]:nth-child(3) div[data-testid="stPopover"] > button:hover {
    text-decoration: underline !important;
    color: #4b5563 !important;
    background-color: transparent !important;
}
.rec-card-title {
    font-size: 0.86rem;
    line-height: 1.2;
    margin: 0 0 0.38rem 0;
}
.rec-card-meta-row {
    display: flex;
    align-items: baseline;
    gap: 1rem;
    margin: 0 0 0.22rem 0;
}
.rec-card-meta {
    font-size: 0.8rem;
    line-height: 1.15;
    margin: 0;
    color: rgba(49, 51, 63, 0.72);
}
.rec-card-meta-score {
    white-space: nowrap;
    font-weight: 500;
    color: rgba(49, 51, 63, 0.82);
}
.rec-panel-hr {
    margin: 0 !important;
    border: none;
    border-top: 1px solid rgba(128, 128, 128, 0.32);
}
div[data-testid="stVerticalBlockBorderWrapper"] div[data-testid="element-container"]:has(.rec-action-row-start) {
    display: none !important;
    height: 0 !important;
    margin: 0 !important;
    padding: 0 !important;
}
div[data-testid="stVerticalBlockBorderWrapper"]:not(:has(.rec-action-row-start)) [data-testid="stHorizontalBlock"] {
    margin-bottom: -1.1rem !important;
}
div[data-testid="stVerticalBlockBorderWrapper"] div[data-testid="element-container"]:has(.rec-panel-hr) {
    margin-top: -0.15rem !important;
    margin-bottom: -0.85rem !important;
    padding: 0 !important;
}
div[data-testid="stVerticalBlockBorderWrapper"] div[data-testid="element-container"]:has(.rec-card-title):not(:first-child) {
    margin-top: -0.15rem !important;
    padding-top: 0 !important;
}
div[data-testid="stVerticalBlockBorderWrapper"] div[data-testid="element-container"]:has(.rec-action-row-start) + div[data-testid="stHorizontalBlock"] [data-testid="stLinkButton"] a {
    font-weight: 600 !important;
    border-radius: 0.35rem !important;
}
div[data-testid="stVerticalBlockBorderWrapper"] div[data-testid="element-container"]:has(.rec-action-row-start) + div[data-testid="stHorizontalBlock"] div[data-testid="stPopover"] {
    width: 100% !important;
}
</style>
"""


def _container_supports_height() -> bool:
    try:
        return "height" in inspect.signature(st.container).parameters
    except (TypeError, ValueError):
        return False


def _accent_class(queue: str) -> str:
    if queue == QUEUE_HIGH_CONFIDENCE:
        return "high-confidence"
    if queue == QUEUE_APPLY_TODAY:
        return "apply-today"
    if queue == QUEUE_APPLY_THIS_WEEK:
        return "apply-this-week"
    if queue == QUEUE_NEEDS_REVIEW:
        return "needs-review"
    return ""


def _row_key_suffix(action: RecommendedAction, *, prefix: str) -> str:
    digest = hashlib.md5(f"{prefix}:{action.entity_key}".encode()).hexdigest()[:10]
    return digest


def _visible_count(visible_key: str, queue: str) -> int:
    if visible_key not in st.session_state:
        st.session_state[visible_key] = DISPLAY_CAP_BY_QUEUE[queue]
    return int(st.session_state[visible_key])


def _render_queue_header(*, label: str, total: int, queue: str) -> None:
    accent = _accent_class(queue)
    help_html = ""
    if queue == QUEUE_NEEDS_REVIEW:
        help_html = help_icon_html(
            *_NEEDS_REVIEW_HELP_LINES,
            tone="needs-review",
            align="right",
        )
    st.markdown(
        f'<div class="rec-queue-header {accent}">'
        f'<span class="rec-queue-header-text">'
        f"{html.escape(label)} · <span class=\"count\">{total}</span>"
        f"</span>"
        f"{help_html}"
        f"</div>",
        unsafe_allow_html=True,
    )


def _render_applied_action(
    action: RecommendedAction,
    *,
    key_prefix: str,
    suffix: str,
) -> None:
    write_enabled = dashboard_write_enabled()
    if st.button(
        "Applied ✓",
        key=f"{key_prefix}_applied_{suffix}",
        disabled=not write_enabled,
        use_container_width=True,
    ):
        if mark_job_applied(
            job_key_v2=action.job_key_v2,
            job_key=action.job_key,
        ):
            st.toast("Marked as Applied", icon="✅")
            st.rerun()


def _render_compact_card(
    action: RecommendedAction,
    *,
    key_prefix: str,
    show_divider: bool,
    show_applied_action: bool = False,
) -> None:
    title = str(action.title or "").strip() or "—"
    company = str(action.company or "").strip() or "—"
    suffix = _row_key_suffix(action, prefix=key_prefix)

    st.markdown(
        f'<p class="rec-card-title"><strong>{html.escape(title)}</strong></p>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="rec-card-meta-row">'
        f'<span class="rec-card-meta">{html.escape(company)}</span>'
        f'<span class="rec-card-meta rec-card-meta-score">AI {action.score:g}/10</span>'
        "</div>",
        unsafe_allow_html=True,
    )

    if show_applied_action:
        st.markdown(
            '<span class="rec-action-row-start"></span>',
            unsafe_allow_html=True,
        )
        c_open, c_applied, c_why = st.columns(
            [5, 2, 2], gap="small", vertical_alignment="center"
        )
        with c_open:
            if is_valid_job_url(action.job_url):
                st.link_button(
                    "Open Job ↗",
                    action.job_url,
                    use_container_width=True,
                    key=f"{key_prefix}_open_{suffix}",
                )
            else:
                st.button(
                    "No link",
                    disabled=True,
                    use_container_width=True,
                    key=f"{key_prefix}_nolink_{suffix}",
                )
        with c_applied:
            _render_applied_action(
                action,
                key_prefix=key_prefix,
                suffix=suffix,
            )
        with c_why:
            render_why_text_action(
                action.full_rationale,
                key=f"{key_prefix}_why_{suffix}",
            )
    else:
        c_open, c_why = st.columns([3, 1], gap="small")
        with c_open:
            if is_valid_job_url(action.job_url):
                st.link_button(
                    "Open Job ↗",
                    action.job_url,
                    use_container_width=True,
                    key=f"{key_prefix}_open_{suffix}",
                )
            else:
                st.button(
                    "No link",
                    disabled=True,
                    use_container_width=True,
                    key=f"{key_prefix}_nolink_{suffix}",
                )
        with c_why:
            render_why_text_action(
                action.full_rationale,
                key=f"{key_prefix}_why_{suffix}",
            )

    if show_divider:
        st.markdown('<hr class="rec-panel-hr">', unsafe_allow_html=True)


def _scroll_container(*, height_px: int):
    if _container_supports_height():
        return st.container(height=height_px, border=True)
    return st.container(border=True)


def _render_queue_panel(
    *,
    label: str,
    queue: str,
    all_actions: list[RecommendedAction],
    total: int,
    key_prefix: str,
) -> None:
    _render_queue_header(label=label, total=total, queue=queue)

    if not _container_supports_height():
        st.warning(
            "Scrollable queue panels require Streamlit 1.30+. "
            "Upgrade streamlit to enable fixed-height panels."
        )

    visible_key = _VISIBLE_STATE_KEYS[queue]
    visible_count = _visible_count(visible_key, queue)
    visible_actions = all_actions[:visible_count]
    panel_height_px = compute_queue_panel_height_px(
        visible_card_count=len(visible_actions),
        has_cards=bool(all_actions),
    )

    with _scroll_container(height_px=panel_height_px):
        if not all_actions:
            st.caption("No actions in this queue.")
        else:
            for index, action in enumerate(visible_actions):
                _render_compact_card(
                    action,
                    key_prefix=key_prefix,
                    show_divider=index < len(visible_actions) - 1,
                    show_applied_action=queue in APPLY_ACTION_QUEUES,
                )

    if total > 0:
        shown = min(visible_count, total)
        st.markdown('<span class="rec-queue-footer-row"></span>', unsafe_allow_html=True)
        caption_col, action_col = st.columns([5, 2], vertical_alignment="center")
        with caption_col:
            st.caption(f"Showing {shown} of {total} jobs")
        with action_col:
            if visible_count < total:
                if st.button(
                    "Load More",
                    key=f"{key_prefix}_load_more",
                    use_container_width=True,
                ):
                    st.session_state[visible_key] = min(
                        visible_count + QUEUE_LOAD_MORE_INCREMENT,
                        total,
                    )
                    st.rerun()
        st.markdown('<span class="rec-queue-panel-end"></span>', unsafe_allow_html=True)


def render_recommended_actions(
    dashboard_df: pd.DataFrame,
    *,
    reference_date=None,
) -> None:
    inject_dashboard_help_css()
    st.markdown(_PANEL_CSS, unsafe_allow_html=True)

    full_result = compute_recommended_actions(
        dashboard_df,
        reference_date=reference_date,
        max_rows_per_queue=None,
    )

    row1_left, row1_right = st.columns(2, gap="medium")
    row2_left, row2_right = st.columns(2, gap="medium")

    with row1_left:
        _render_queue_panel(
            label=HIGH_CONFIDENCE_LABEL,
            queue=QUEUE_HIGH_CONFIDENCE,
            all_actions=full_result.high_confidence,
            total=full_result.high_confidence_total,
            key_prefix="high_confidence",
        )
    with row1_right:
        _render_queue_panel(
            label=APPLY_TODAY_LABEL,
            queue=QUEUE_APPLY_TODAY,
            all_actions=full_result.apply_today,
            total=full_result.apply_today_total,
            key_prefix="apply_today",
        )
    with row2_left:
        _render_queue_panel(
            label=APPLY_THIS_WEEK_LABEL,
            queue=QUEUE_APPLY_THIS_WEEK,
            all_actions=full_result.apply_this_week,
            total=full_result.apply_this_week_total,
            key_prefix="apply_this_week",
        )
    with row2_right:
        _render_queue_panel(
            label=NEEDS_REVIEW_LABEL,
            queue=QUEUE_NEEDS_REVIEW,
            all_actions=full_result.needs_review,
            total=full_result.needs_review_total,
            key_prefix="needs_review",
        )


def render_recommended_actions_section(
    dashboard_df: pd.DataFrame,
    *,
    reference_date=None,
) -> None:
    st.markdown("---")
    st.subheader(RECOMMENDED_ACTIONS_TITLE)
    render_recommended_actions(dashboard_df, reference_date=reference_date)
