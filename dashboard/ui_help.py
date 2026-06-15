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
    font-size: 1.5rem;
    font-weight: 600;
    line-height: 1.2;
    color: rgb(49, 51, 63);
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
</style>
"""

_CSS_INJECTED_KEY = "_dash_help_css_injected"


def inject_dashboard_help_css() -> None:
    if st.session_state.get(_CSS_INJECTED_KEY):
        return
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


def render_subheader_with_help(title: str, *help_lines: str) -> None:
    """Section title with inline info icon (replaces subheader + caption)."""
    inject_dashboard_help_css()
    st.markdown(
        '<div class="dash-section-header">'
        f'<span class="dash-section-header-text">{html.escape(title)}</span>'
        f"{help_icon_html(*help_lines)}"
        "</div>",
        unsafe_allow_html=True,
    )
