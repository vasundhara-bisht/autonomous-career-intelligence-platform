"""Job Outreach prefill agent (Phase 3D.3).

DB-driven enrichment only — no Playwright, no LinkedIn scraping.

Builds an ingest draft dict (same shape as the Hiring Signal draft stored in
_INGEST_DRAFT_KEY) from a JobOutreachContext, then generates an AI outreach
message.

The job description is passed to generate_outreach_message() as the `notes`
context parameter for AI use only.  It is never written to the draft dict or
persisted in the outreach record — Notes defaults to empty and is
operator-only.
"""

from __future__ import annotations

import traceback

from db.engine import get_session
from db.read.job_outreach import JobOutreachContext, load_job_outreach_context

try:
    from agent.outreach_message_generate import generate_outreach_message
except ImportError:  # pragma: no cover
    generate_outreach_message = None  # type: ignore[assignment]


def _resolve_person_name(ctx: JobOutreachContext) -> str:
    return ctx.recruiter_name or ctx.hiring_manager or ""


def _resolve_designation(ctx: JobOutreachContext) -> str:
    return ctx.recruiter_title or ""


def _resolve_company(ctx: JobOutreachContext) -> str:
    return ctx.recruiter_company or ctx.company or ""


def run_job_outreach_prefill(
    job_key_v2: str,
    candidate_profile: str = "",
) -> tuple[dict[str, str], str]:
    """Load job context from DB and build an outreach draft with AI message.

    Returns (draft, warning).

    draft is a dict with the same keys used by the Hiring Signal ingest draft
    stored in _INGEST_DRAFT_KEY.  outreach_type is always "job_outreach" and
    hiring_signal_type is always "job_listing".  notes is always "".

    warning is a non-empty string when something degraded (e.g. no description
    found, no recruiter found, AI generation failed).  An empty warning means
    enrichment succeeded fully.

    Returns ({}, error_message) when the job is not found in the database.
    """
    try:
        with get_session() as session:
            ctx = load_job_outreach_context(session, job_key_v2)
    except Exception:
        return {}, f"Database error loading job '{job_key_v2}'."

    if ctx is None:
        return {}, f"Job '{job_key_v2}' not found in database."

    warnings: list[str] = []

    if not ctx.description:
        warnings.append("No job description found — AI message context is limited.")

    if not ctx.recruiter_name and not ctx.hiring_manager:
        warnings.append("No recruiter or hiring manager found — Person Name left blank.")

    person_name = _resolve_person_name(ctx)
    designation = _resolve_designation(ctx)
    company = _resolve_company(ctx)

    draft: dict[str, str] = {
        "person_name": person_name,
        "designation": designation,
        "company": company,
        "hiring_signal_type": "job_listing",
        "hiring_signal_url": "",
        "outreach_type": "job_outreach",
        "opportunity_id": ctx.job_key_v2,
        "opportunity_url": ctx.link,
        "notes": "",
    }

    outreach_message = ""
    if generate_outreach_message is not None:
        try:
            msg, ok = generate_outreach_message(
                person_name=person_name,
                designation=designation,
                company=company,
                notes=ctx.description,  # AI context only — never persisted
                hiring_signal_type="job_listing",
                candidate_profile=candidate_profile,
            )
            if ok and msg:
                outreach_message = msg
            elif not ok:
                warnings.append("AI message generation failed — field left blank.")
        except Exception:
            warnings.append("AI message generation failed — field left blank.")

    draft["outreach_message"] = outreach_message

    warning = "  ".join(warnings)
    return draft, warning
