"""UI craftsmanship showcase — standalone, no backend required.

Renders the same reusable help-icon / section-header component
(`dashboard/ui_help.py`) used throughout the real dashboard, including the
amber contextual-help pattern placed directly beside a disabled action
(e.g. "Fetch Details" in Demo Mode).

This file has no dependency on any removed module — it only needs
Streamlit and the kept `dashboard/ui_help.py`.

Run:

    pip install -r requirements.txt
    streamlit run showcase/ui_pattern_demo.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "dashboard"))

from ui_help import (  # noqa: E402
    help_icon_html,
    render_section_heading,
    render_subheader_with_help,
)

st.set_page_config(page_title="UI Pattern Showcase", layout="centered")

st.title("UI Pattern Showcase")
st.caption(
    "A standalone excerpt of the dashboard's help-icon / section-header "
    "component — not the product itself. See docs/ABOUT_THIS_REPO.md."
)

render_section_heading("Outreach Intelligence")

st.write("")
st.markdown(
    '<div style="display: flex; align-items: center; gap: 0.5rem;">'
    '<button disabled style="padding: 0.4rem 0.9rem; border-radius: 0.4rem; '
    'border: 1px solid rgba(49,51,63,0.2); background: rgba(49,51,63,0.06); '
    'color: rgba(49,51,63,0.5); font-weight: 600;">Fetch Details</button>'
    f"{help_icon_html('Unavailable in Demo Mode — automation and external systems are disabled.', tone='warning')}"
    "</div>",
    unsafe_allow_html=True,
)
st.caption(
    "Illustrates the amber contextual-help icon sitting immediately beside "
    "a disabled action, at natural button width — the layout pattern "
    "described in the README."
)

st.write("")
render_subheader_with_help(
    "Recommended Actions",
    "Four-queue command center: High Confidence, Apply Today, Apply This Week, Needs Review.",
)

k1, k2, k3 = st.columns(3)
k1.metric("High Confidence", "12")
k2.metric("Apply Today", "5")
k3.metric("Needs Review", "3")
