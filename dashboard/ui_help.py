"""Reusable dashboard help-icon and section-header patterns."""

from __future__ import annotations

import html

import streamlit as st

_DASH_HELP_CSS = """
<style>
.dash-section-header {
    display: flex;
    align-items: center;
    gap: 0.45rem;
    margin: 0 0 0.75rem 0;
}
.dash-section-header-text {
    font-size: 1.575rem;
    font-weight: 650;
    line-height: 1.2;
    letter-spacing: 0.02em;
    text-transform: uppercase;
    color: rgb(49, 51, 63);
}
.dash-subsection-header-text {
    font-size: 1.05rem;
    font-weight: 650;
    line-height: 1.25;
    letter-spacing: 0.02em;
    text-transform: uppercase;
    color: rgb(49, 51, 63);
    margin: 0 0 0.5rem 0;
}
.dash-help {
    position: relative;
    display: inline-flex;
    align-items: center;
    flex-shrink: 0;
}
.dash-help-icon {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 1.15rem;
    height: 1.15rem;
    border-radius: 999px;
    font-size: 0.72rem;
    font-weight: 700;
    line-height: 1;
    color: rgba(49, 51, 63, 0.72);
    background: rgba(128, 128, 128, 0.14);
    cursor: help;
}
.dash-help-icon.needs-review-tone {
    color: rgba(130, 90, 0, 0.92);
    background: rgba(200, 145, 0, 0.14);
}
.dash-help-tooltip {
    visibility: hidden;
    opacity: 0;
    position: absolute;
    z-index: 20;
    top: calc(100% + 0.35rem);
    left: 0;
    width: max-content;
    max-width: 18rem;
    padding: 0.45rem 0.55rem;
    border-radius: 0.35rem;
    border: 1px solid rgba(128, 128, 128, 0.28);
    background: rgba(255, 255, 255, 0.98);
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.12);
    font-size: 0.74rem;
    font-weight: 500;
    line-height: 1.35;
    color: rgba(49, 51, 63, 0.88);
    pointer-events: none;
    transition: opacity 0.12s ease;
}
.dash-help.align-right .dash-help-tooltip {
    left: auto;
    right: 0;
}
.dash-help:hover .dash-help-tooltip,
.dash-help:focus-within .dash-help-tooltip {
    visibility: visible;
    opacity: 1;
}
.dash-refresh-labels {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: 0.35rem 2rem;
    margin: -0.25rem 0 0.75rem 0;
    font-size: 0.875rem;
    font-weight: 400;
    line-height: 1.4;
    color: rgba(49, 51, 63, 0.6);
}
.dash-field-label {
    display: flex;
    align-items: center;
    gap: 0.35rem;
    margin: 0 0 0.35rem 0;
    font-size: 0.875rem;
    font-weight: 500;
    color: rgb(49, 51, 63);
}
.mon-status-badge {
    display: inline-block;
    padding: 0.2rem 0.55rem;
    border-radius: 0.35rem;
    font-size: 0.92rem;
    font-weight: 650;
    line-height: 1.35;
    white-space: nowrap;
}
.mon-badge-ok {
    color: rgb(9, 94, 52);
    background: rgba(33, 195, 84, 0.16);
}
.mon-badge-warn {
    color: rgb(130, 90, 0);
    background: rgba(255, 193, 7, 0.2);
}
.mon-badge-error {
    color: rgb(140, 30, 30);
    background: rgba(255, 75, 75, 0.16);
}
.mon-badge-neutral {
    color: rgba(49, 51, 63, 0.78);
    background: rgba(128, 128, 128, 0.14);
}
.mon-status-banner {
    padding: 0.65rem 0.85rem;
    border-radius: 0.45rem;
    margin: 0.35rem 0 0.85rem 0;
    font-size: 0.9rem;
    font-weight: 550;
    line-height: 1.4;
}
.mon-banner-green {
    color: rgb(9, 94, 52);
    background: rgba(33, 195, 84, 0.12);
    border: 1px solid rgba(33, 195, 84, 0.28);
}
.mon-banner-orange {
    color: rgb(130, 90, 0);
    background: rgba(255, 193, 7, 0.12);
    border: 1px solid rgba(255, 193, 7, 0.35);
}
.mon-banner-red {
    color: rgb(140, 30, 30);
    background: rgba(255, 75, 75, 0.1);
    border: 1px solid rgba(255, 75, 75, 0.28);
}
.mon-banner-details {
    margin-top: 0.35rem;
    font-size: 0.8rem;
    font-weight: 500;
    line-height: 1.35;
    opacity: 0.92;
}
.mon-provider-card-title {
    font-size: 0.95rem;
    font-weight: 700;
    margin: 0 0 0.5rem 0;
    color: rgb(49, 51, 63);
}
.mon-metric-row-label {
    font-size: 0.78rem;
    color: rgba(49, 51, 63, 0.68);
    margin-bottom: 0.1rem;
}
.mon-metric-row-value {
    font-size: 0.98rem;
    font-weight: 650;
    color: rgb(49, 51, 63);
    margin-bottom: 0.55rem;
}
</style>
"""

_CSS_INJECTED_KEY = "_dash_help_css_injected"


def inject_dashboard_help_css() -> None:
    # Re-inject on every rerun: Streamlit clears prior <style> blocks on st.rerun().
    st.markdown(_DASH_HELP_CSS, unsafe_allow_html=True)
    st.session_state[_CSS_INJECTED_KEY] = True


def help_icon_html(
    *lines: str,
    tone: str = "neutral",
    align: str = "left",
) -> str:
    tooltip = "<br>".join(html.escape(line) for line in lines if line.strip())
    aria = html.escape(lines[0] if lines else "")
    tone_class = " needs-review-tone" if tone == "needs-review" else ""
    align_class = " align-right" if align == "right" else ""
    return (
        f'<span class="dash-help{align_class}" tabindex="0" aria-label="{aria}">'
        f'<span class="dash-help-icon{tone_class}" aria-hidden="true">i</span>'
        f'<span class="dash-help-tooltip">{tooltip}</span>'
        "</span>"
    )


def normalize_section_title(title: str) -> str:
    return str(title or "").strip().upper()


def render_section_heading(title: str) -> None:
    """Section title without help icon (uppercase via shared styling)."""
    inject_dashboard_help_css()
    display_title = normalize_section_title(title)
    st.markdown(
        '<div class="dash-section-header">'
        f'<span class="dash-section-header-text">{html.escape(display_title)}</span>'
        "</div>",
        unsafe_allow_html=True,
    )


def render_subsection_heading(title: str) -> None:
    """Smaller uppercase subsection title inside a section."""
    inject_dashboard_help_css()
    display_title = normalize_section_title(title)
    st.markdown(
        f'<p class="dash-subsection-header-text">{html.escape(display_title)}</p>',
        unsafe_allow_html=True,
    )


def render_subheader_with_help(title: str, *help_lines: str) -> None:
    """Section title with inline info icon (replaces subheader + caption)."""
    inject_dashboard_help_css()
    display_title = normalize_section_title(title)
    st.markdown(
        '<div class="dash-section-header">'
        f'<span class="dash-section-header-text">{html.escape(display_title)}</span>'
        f"{help_icon_html(*help_lines)}"
        "</div>",
        unsafe_allow_html=True,
    )


def render_refresh_labels_row(acquisition_label: str, monitoring_label: str) -> None:
    """Side-by-side acquisition and monitoring refresh captions (wraps on narrow viewports)."""
    inject_dashboard_help_css()
    st.markdown(
        '<div class="dash-refresh-labels">'
        f"<span>Last acquisition refresh: {html.escape(acquisition_label)}</span>"
        f"<span>Last monitoring refresh: {html.escape(monitoring_label)}</span>"
        "</div>",
        unsafe_allow_html=True,
    )


def render_field_label_with_help(label: str, *help_lines: str) -> None:
    """Form field label with inline info icon (pair with label_visibility=collapsed input)."""
    inject_dashboard_help_css()
    st.markdown(
        '<div class="dash-field-label">'
        f"<span>{html.escape(label)}</span>"
        f"{help_icon_html(*help_lines)}"
        "</div>",
        unsafe_allow_html=True,
    )


def render_metric_label_with_help(label: str, value: str, *help_lines: str) -> str:
    """HTML block for a metric row label + value + optional tooltip."""
    help_html = help_icon_html(*help_lines) if help_lines else ""
    return (
        '<div class="mon-metric-row">'
        '<div class="mon-metric-row-label">'
        f"{html.escape(label)}{help_html}"
        "</div>"
        f'<div class="mon-metric-row-value">{html.escape(value)}</div>'
        "</div>"
    )
