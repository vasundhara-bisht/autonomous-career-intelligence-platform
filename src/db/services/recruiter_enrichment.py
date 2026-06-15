"""Dashboard Hiring Manager → recruiter CRM enrichment (Phase 3B)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models.schema import Job, Recruiter, RecruiterJobLink

RECRUITER_SOURCE_JOB_EDITOR = "job_editor"
NOT_SPECIFIED_HIRING_MANAGER = "Not Specified"


def _now_utc_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def generate_recruiter_key(name: str) -> str:
    return str(name or "").strip().lower()


def is_valid_recruiter_name(name: str) -> bool:
    text = str(name or "").strip()
    if not text:
        return False
    return text.lower() not in ("not specified", "unknown", "nan")


def normalize_hiring_manager(value: object) -> str:
    text = str(value or "").strip()
    if not text or text.lower() in ("not specified", "unknown", "nan", "none"):
        return NOT_SPECIFIED_HIRING_MANAGER
    return text


@dataclass(frozen=True)
class RecruiterEnrichmentResult:
    outcome: str
    recruiter_created: bool = False
    link_added: bool = False


def sync_recruiter_from_hiring_manager(
    session: Session,
    *,
    job_id: int,
    hiring_manager: str,
    company: str = "",
    job_source: str = "",
) -> RecruiterEnrichmentResult:
    """Update jobs.hiring_manager and append recruiter + link when name is valid."""
    job = session.get(Job, job_id)
    if job is None:
        return RecruiterEnrichmentResult(outcome="skipped")

    normalized = normalize_hiring_manager(hiring_manager)
    job.hiring_manager = normalized

    if not is_valid_recruiter_name(normalized):
        if normalized == NOT_SPECIFIED_HIRING_MANAGER:
            return RecruiterEnrichmentResult(outcome="cleared_display")
        return RecruiterEnrichmentResult(outcome="skipped")

    recruiter_key = generate_recruiter_key(normalized)
    now = _now_utc_naive()
    company_text = str(company or "").strip()
    source_text = str(job_source or "").strip()

    recruiter = session.execute(
        select(Recruiter).where(Recruiter.recruiter_key == recruiter_key)
    ).scalar_one_or_none()

    recruiter_created = False
    if recruiter is None:
        recruiter = Recruiter(
            recruiter_key=recruiter_key,
            recruiter_name=normalized,
            current_company=company_text or None,
            source=RECRUITER_SOURCE_JOB_EDITOR or None,
            first_seen=now,
            last_seen=now,
            jobs_connected=0,
            recruiter_stage="discovered",
            outreach_sent=False,
            recruiter_replied=False,
            notes="",
            last_outreach_date=None,
            last_response_date=None,
            touchpoint_count=0,
            last_interaction_note=None,
            currently_active=True,
        )
        session.add(recruiter)
        session.flush()
        recruiter_created = True
    else:
        recruiter.recruiter_name = normalized
        recruiter.last_seen = now
        recruiter.currently_active = True
        if company_text and not str(recruiter.current_company or "").strip():
            recruiter.current_company = company_text

    link_exists = session.execute(
        select(RecruiterJobLink.id).where(
            RecruiterJobLink.recruiter_id == recruiter.id,
            RecruiterJobLink.job_id == job_id,
        )
    ).scalar_one_or_none()

    link_added = False
    if link_exists is None:
        session.add(
            RecruiterJobLink(
                recruiter_id=recruiter.id,
                job_id=job_id,
                linked_at=now,
            )
        )
        link_added = True

    outcome = "linked" if link_added else "updated_display"
    return RecruiterEnrichmentResult(
        outcome=outcome,
        recruiter_created=recruiter_created,
        link_added=link_added,
    )
