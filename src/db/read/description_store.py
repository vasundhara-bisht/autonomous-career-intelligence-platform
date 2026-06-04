"""Load job description cache from SQLite (D4 pipeline read)."""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from db.bootstrap import ensure_database_ready
from db.models.schema import Job, JobDescription
from db.read.engine import get_read_session

_log = logging.getLogger(__name__)


def _format_last_updated(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.strftime("%Y-%m-%d %H:%M:%S")


def populate_description_store_from_session(session: Session, store) -> None:
    """
    Fill a DescriptionStore from job_descriptions + jobs.

    Uses latest row per job_key_v2 when duplicates exist.
    """
    from agent.job_description_persistence import _is_persistable_description

    rows = session.execute(
        select(
            Job.job_key,
            JobDescription.job_key_v2,
            JobDescription.description,
            JobDescription.source,
            JobDescription.last_updated,
        ).join(Job, Job.id == JobDescription.job_id)
    ).all()

    best_by_v2: dict[str, tuple] = {}
    for legacy_key, v2_key, desc, source, last_updated in rows:
        v2 = str(v2_key or "").strip()
        legacy = str(legacy_key or "").strip()
        if not _is_persistable_description(desc):
            continue
        ts = _format_last_updated(last_updated)
        key = v2 or legacy
        if not key:
            continue
        prev = best_by_v2.get(key)
        if prev is not None and prev[0] >= ts:
            continue
        best_by_v2[key] = (
            ts,
            legacy,
            v2,
            {
                "description": str(desc).strip(),
                "last_updated": ts,
                "source": str(source or "").strip(),
                "job_key": legacy,
                "job_key_v2": v2,
            },
        )

    for _ts, legacy, v2, record in best_by_v2.values():
        store.put(legacy_key=legacy, v2_key=v2, record=record)


def load_description_store_from_db(store) -> None:
    ensure_database_ready()
    with get_read_session() as session:
        populate_description_store_from_session(session, store)
    _log.info(
        "Pipeline description store: SQLite (v2=%s legacy=%s)",
        len(store.by_v2),
        len(store.by_legacy),
    )
