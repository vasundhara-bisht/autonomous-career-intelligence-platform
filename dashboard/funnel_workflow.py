"""CRM-style workflow presentation for job search progression (dashboard-only)."""

from __future__ import annotations

import html
from typing import TYPE_CHECKING

import streamlit as st

from funnel import APPLICATION_STAGES, OUTCOME_STAGES

if TYPE_CHECKING:
    from funnel import ProgressionFunnelCounts

JOB_SEARCH_PROGRESSION_TITLE = "Job Search Progression"

_WORKFLOW_CSS = """
<style>
.job-search-progression {
    margin: 0.25rem 0 1rem 0;
}
.job-search-progression .progression-row {
    display: flex;
    flex-direction: row;
    flex-wrap: nowrap;
    align-items: stretch;
    gap: 0;
    overflow-x: auto;
    padding-bottom: 0.35rem;
}
.job-search-progression .arrow {
    display: flex;
    align-items: center;
    justify-content: center;
    min-width: 1.25rem;
    color: rgba(128, 128, 128, 0.85);
    font-size: 1.1rem;
    font-weight: 600;
    flex-shrink: 0;
    padding: 0 0.15rem;
}
.job-search-progression .stage-card {
    flex: 1 1 0;
    min-width: 6.5rem;
    max-width: 11rem;
    border: 1px solid rgba(128, 128, 128, 0.35);
    border-radius: 0.5rem;
    padding: 0.65rem 0.5rem;
    text-align: center;
    background: rgba(128, 128, 128, 0.06);
    flex-shrink: 0;
}
.job-search-progression .stage-card.discovery {
    min-width: 7.5rem;
}
.job-search-progression .stage-card.empty {
    opacity: 0.55;
}
.job-search-progression .stage-label {
    font-size: 0.72rem;
    font-weight: 600;
    line-height: 1.2;
    margin-bottom: 0.35rem;
    color: inherit;
}
.job-search-progression .stage-count {
    font-size: 1.65rem;
    font-weight: 700;
    line-height: 1.1;
}
.job-search-progression .stage-sub {
    font-size: 0.68rem;
    margin-top: 0.35rem;
    opacity: 0.85;
    line-height: 1.3;
}
.job-search-progression .outcomes-section {
    margin-top: 1rem;
}
.job-search-progression .outcomes-label {
    font-size: 0.8rem;
    font-weight: 600;
    margin-bottom: 0.5rem;
    opacity: 0.9;
}
.job-search-progression .outcomes-row {
    display: flex;
    flex-direction: row;
    flex-wrap: nowrap;
    gap: 0.75rem;
}
.job-search-progression .outcome-card {
    min-width: 6.5rem;
    max-width: 9rem;
    border: 1px solid rgba(128, 128, 128, 0.35);
    border-left: 3px solid rgba(128, 128, 128, 0.5);
    border-radius: 0.5rem;
    padding: 0.65rem 0.75rem;
    text-align: center;
    background: rgba(128, 128, 128, 0.04);
}
.job-search-progression .outcome-card.empty {
    opacity: 0.55;
}
</style>
"""


def _escape(text: object) -> str:
    return html.escape(str(text))


def _count_for_stage(counts: ProgressionFunnelCounts, stage: str) -> int:
    if stage == "Discovery":
        return counts.discovery_total
    app_row = counts.application_df.loc[counts.application_df["stage"] == stage]
    if not app_row.empty:
        return int(app_row.iloc[0]["count"])
    out_row = counts.outcomes_df.loc[counts.outcomes_df["stage"] == stage]
    if not out_row.empty:
        return int(out_row.iloc[0]["count"])
    return 0


def _pct_for_stage(counts: ProgressionFunnelCounts, stage: str) -> float:
    if stage == "Discovery":
        if counts.total_filtered <= 0:
            return 0.0
        return round((counts.discovery_total / counts.total_filtered) * 100, 1)
    for frame in (counts.application_df, counts.outcomes_df):
        row = frame.loc[frame["stage"] == stage]
        if not row.empty:
            return float(row.iloc[0]["pct_of_filtered"])
    return 0.0


def _stage_card(
    *,
    label: str,
    count: int,
    pct: float,
    subline: str = "",
    extra_class: str = "",
) -> str:
    empty_class = " empty" if count == 0 else ""
    title = _escape(f"{pct}% of visible jobs")
    sub_html = (
        f'<div class="stage-sub">{_escape(subline)}</div>' if subline else ""
    )
    return (
        f'<div class="stage-card{empty_class}{extra_class}" title="{title}">'
        f'<div class="stage-label">{_escape(label)}</div>'
        f'<div class="stage-count">{count}</div>'
        f"{sub_html}"
        f"</div>"
    )


def build_workflow_html(counts: ProgressionFunnelCounts) -> str:
    """Build horizontal CRM-style progression cards with arrows."""
    progression_stages = ("Discovery",) + APPLICATION_STAGES
    parts: list[str] = [
        _WORKFLOW_CSS,
        '<div class="job-search-progression">',
        '<div class="progression-row">',
    ]

    for index, stage in enumerate(progression_stages):
        if index > 0:
            parts.append('<div class="arrow" aria-hidden="true">→</div>')

        count = _count_for_stage(counts, stage)
        pct = _pct_for_stage(counts, stage)
        extra = " discovery" if stage == "Discovery" else ""
        subline = ""
        if stage == "Discovery":
            subline = f"New: {counts.new_count} · Saved: {counts.saved_count}"

        parts.append(
            _stage_card(
                label=stage,
                count=count,
                pct=pct,
                subline=subline,
                extra_class=extra,
            )
        )

    parts.append("</div>")
    parts.append('<div class="outcomes-section">')
    parts.append(f'<div class="outcomes-label">{_escape("Outcomes")}</div>')
    parts.append('<div class="outcomes-row">')

    for stage in OUTCOME_STAGES:
        count = _count_for_stage(counts, stage)
        pct = _pct_for_stage(counts, stage)
        empty_class = " empty" if count == 0 else ""
        title = _escape(f"{pct}% of visible jobs")
        parts.append(
            f'<div class="outcome-card{empty_class}" title="{title}">'
            f'<div class="stage-label">{_escape(stage)}</div>'
            f'<div class="stage-count">{count}</div>'
            f"</div>"
        )

    parts.append("</div></div></div>")
    return "\n".join(parts)


def render_job_search_progression_workflow(counts: ProgressionFunnelCounts) -> None:
    st.markdown(build_workflow_html(counts), unsafe_allow_html=True)
