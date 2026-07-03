"""Pipeline stage promotion helpers (monitor / automation writers)."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from agent.pipeline_stages import is_discovery_pipeline_stage
from db.models.schema import Job, UserJobState
from db.services.lifecycle_write import set_monitor_exempt


def _now_utc_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def promote_job_to_applied_if_eligible(session: Session, job: Job) -> bool:
    """
    Promote discovery-stage jobs to Applied when LinkedIn shows user-applied state.

    One-way only: never downgrades Applied+ stages. Does not invoke dashboard CSV export.
    """
    state = session.get(UserJobState, job.id)
    current_stage = str(state.pipeline_stage or "New").strip() if state is not None else "New"

    if not is_discovery_pipeline_stage(current_stage):
        return False

    if state is not None and bool(state.rejected):
        return False

    notes = str(state.notes or "").strip() if state is not None else ""
    interview = bool(state.interview) if state is not None else False
    offer = bool(state.offer) if state is not None else False

    payload = {
        "applied": True,
        "rejected": False,
        "interview": interview,
        "offer": offer,
        "notes": notes or None,
        "pipeline_stage": "Applied",
        "updated_at": _now_utc_naive(),
    }
    if state is not None:
        for key, value in payload.items():
            setattr(state, key, value)
    else:
        session.add(UserJobState(job_id=job.id, **payload))

    set_monitor_exempt(session, job)
    return True
