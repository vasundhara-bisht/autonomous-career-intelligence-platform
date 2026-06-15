"""CRM-style workflow presentation for recruiter relationship progression."""

from __future__ import annotations

import html
from typing import TYPE_CHECKING

import streamlit as st

from recruiter_stages import ENGAGEMENT_STAGES, OUTCOME_STAGES, recruiter_stage_label

if TYPE_CHECKING:
    from recruiter_funnel import RecruiterProgressionCounts

RECRUITER_RELATIONSHIP_PROGRESSION_TITLE = "Relationship Progression"

_WORKFLOW_CSS = """
<style>
.recruiter-relationship-progression {
    margin: 0.25rem 0 1rem 0;
}
.recruiter-relationship-progression .progression-row {
    display: flex;
    flex-direction: row;
    flex-wrap: nowrap;
    align-items: stretch;
    gap: 0;
    overflow-x: auto;
    padding-bottom: 0.35rem;
}
.recruiter-relationship-progression .arrow {
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
.recruiter-relationship-progression .stage-card {
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
.recruiter-relationship-progression .stage-card.empty {
    opacity: 0.55;
}
.recruiter-relationship-progression .stage-label {
    font-size: 0.72rem;
    font-weight: 600;
    line-height: 1.2;
    margin-bottom: 0.35rem;
    color: inherit;
}
.recruiter-relationship-progression .stage-count {
    font-size: 1.65rem;
    font-weight: 700;
    line-height: 1.1;
}
.recruiter-relationship-progression .outcomes-section {
    margin-top: 1rem;
}
.recruiter-relationship-progression .outcomes-label {
    font-size: 0.8rem;
    font-weight: 600;
    margin-bottom: 0.5rem;
    opacity: 0.9;
}
.recruiter-relationship-progression .outcomes-row {
    display: flex;
    flex-direction: row;
    flex-wrap: nowrap;
    gap: 0.75rem;
}
.recruiter-relationship-progression .outcome-card {
    min-width: 6.5rem;
    max-width: 9rem;
    border: 1px solid rgba(128, 128, 128, 0.35);
    border-left: 3px solid rgba(128, 128, 128, 0.5);
    border-radius: 0.5rem;
    padding: 0.65rem 0.75rem;
    text-align: center;
    background: rgba(128, 128, 128, 0.04);
}
.recruiter-relationship-progression .outcome-card.empty {
    opacity: 0.55;
}
</style>
"""


def _escape(text: object) -> str:
    return html.escape(str(text))


def _count_for_stage(counts: RecruiterProgressionCounts, stage: str) -> int:
    return int(counts.stage_counts.get(stage, 0))


def _pct_for_stage(counts: RecruiterProgressionCounts, stage: str) -> float:
    if counts.total <= 0:
        return 0.0
    return round((_count_for_stage(counts, stage) / counts.total) * 100, 1)


def _stage_card(*, label: str, count: int, pct: float) -> str:
    empty_class = " empty" if count == 0 else ""
    title = _escape(f"{pct}% of tracked recruiters")
    return (
        f'<div class="stage-card{empty_class}" title="{title}">'
        f'<div class="stage-label">{_escape(label)}</div>'
        f'<div class="stage-count">{count}</div>'
        f"</div>"
    )


def build_recruiter_workflow_html(counts: RecruiterProgressionCounts) -> str:
    """Build horizontal CRM-style recruiter progression cards with arrows."""
    parts: list[str] = [
        _WORKFLOW_CSS,
        '<div class="recruiter-relationship-progression">',
        '<div class="progression-row">',
    ]

    for index, stage in enumerate(ENGAGEMENT_STAGES):
        if index > 0:
            parts.append('<div class="arrow" aria-hidden="true">→</div>')
        count = _count_for_stage(counts, stage)
        pct = _pct_for_stage(counts, stage)
        parts.append(
            _stage_card(
                label=recruiter_stage_label(stage),
                count=count,
                pct=pct,
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
        title = _escape(f"{pct}% of tracked recruiters")
        parts.append(
            f'<div class="outcome-card{empty_class}" title="{title}">'
            f'<div class="stage-label">{_escape(recruiter_stage_label(stage))}</div>'
            f'<div class="stage-count">{count}</div>'
            f"</div>"
        )

    parts.append("</div></div></div>")
    return "\n".join(parts)


def render_recruiter_relationship_progression_workflow(
    counts: RecruiterProgressionCounts,
) -> None:
    st.markdown(build_recruiter_workflow_html(counts), unsafe_allow_html=True)
