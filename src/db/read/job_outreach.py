"""DB read layer for Job Outreach enrichment (Phase 3D.3).

Returns a single snapshot of job + description + recruiter from the database.
No Playwright. No network I/O.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models.schema import Job, JobDescription, Recruiter, RecruiterJobLink


@dataclass
class JobOutreachContext:
    """All DB-sourced data needed to prefill and enrich a Job Outreach attempt."""

    job_key_v2: str
    title: str
    company: str
    location: str
    posted_at_date: str
    link: str
    description: str          # from job_descriptions, "" when not fetched yet
    recruiter_name: str       # from recruiters via RecruiterJobLink, "" when absent
    recruiter_title: str
    recruiter_company: str
    hiring_manager: str       # from jobs.hiring_manager, fallback for person_name


def _str(value: object) -> str:
    return str(value or "").strip()


def load_job_outreach_context(
    session: Session, job_key_v2: str
) -> JobOutreachContext | None:
    """Load job + latest description + first linked recruiter for Job Outreach.

    Returns None when no job with the given job_key_v2 exists.
    description and recruiter fields are empty strings when not available.
    """
    job_row = session.execute(
        select(Job).where(Job.job_key_v2 == job_key_v2)
    ).scalar_one_or_none()

    if job_row is None:
        return None

    # Latest description for this job (may not exist).
    desc_row = session.execute(
        select(JobDescription)
        .where(JobDescription.job_id == job_row.id)
        .order_by(JobDescription.last_updated.desc())
        .limit(1)
    ).scalar_one_or_none()
    description = _str(desc_row.description if desc_row else "")

    # First linked recruiter ordered by link recency (may not exist).
    link_row = session.execute(
        select(RecruiterJobLink)
        .where(RecruiterJobLink.job_id == job_row.id)
        .order_by(RecruiterJobLink.linked_at.desc())
        .limit(1)
    ).scalar_one_or_none()

    recruiter_name = ""
    recruiter_title = ""
    recruiter_company = ""
    if link_row is not None:
        rec = session.execute(
            select(Recruiter).where(Recruiter.id == link_row.recruiter_id)
        ).scalar_one_or_none()
        if rec is not None:
            recruiter_name = _str(rec.recruiter_name)
            recruiter_title = _str(rec.recruiter_title)
            recruiter_company = _str(rec.recruiter_company)

    return JobOutreachContext(
        job_key_v2=_str(job_row.job_key_v2),
        title=_str(job_row.title),
        company=_str(job_row.company),
        location=_str(job_row.location),
        posted_at_date=_str(job_row.posted_at_date),
        link=_str(job_row.link),
        description=description,
        recruiter_name=recruiter_name,
        recruiter_title=recruiter_title,
        recruiter_company=recruiter_company,
        hiring_manager=_str(job_row.hiring_manager),
    )
