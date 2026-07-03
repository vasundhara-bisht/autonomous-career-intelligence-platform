"""Outreach Intelligence persistence (dashboard writes only)."""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from db.bootstrap import ensure_database_ready
from db.engine import get_session
from db.models.schema import OutreachAttempt
from db.read.engine import dashboard_write_enabled

_log = logging.getLogger(__name__)

_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_EDITABLE_COLUMNS = (
    "status",
    "follow_up_date",
    "notes",
    "date_contacted",
    "hiring_signal_type",
    "hiring_signal_url",
)
_HIRING_SIGNAL_TYPES = frozenset(
    {
        "linkedin_hiring_post",
        "founder_post",
        "recruiter_message",
        "whatsapp_referral",
        "personal_referral",
        "mentor_referral",
        "direct_outreach",
        "other",
        "job_listing",
    }
)


def _now_utc_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _optional_text(value: Any) -> str | None:
    text = _text(value)
    return text or None


def _normalize_iso_date(value: Any, *, field_name: str) -> str | None:
    text = _text(value)
    if not text:
        return None
    if not _ISO_DATE_RE.match(text):
        raise ValueError(f"{field_name} must be YYYY-MM-DD")
    return text


def _validate_hiring_signal_type(value: Any, *, required: bool) -> str | None:
    text = _text(value)
    if not text:
        if required:
            raise ValueError("missing required field: hiring_signal_type")
        return None
    if text not in _HIRING_SIGNAL_TYPES:
        raise ValueError("invalid hiring_signal_type")
    return text


def validate_outreach_payload(payload: dict[str, Any], *, require_all: bool = True) -> None:
    required = (
        "person_name",
        "company",
        "outreach_channel",
        "status",
        "date_contacted",
        "hiring_signal_type",
    )
    if require_all:
        for key in required:
            if key == "hiring_signal_type":
                _validate_hiring_signal_type(payload.get(key), required=True)
            elif not _text(payload.get(key)):
                raise ValueError(f"missing required field: {key}")
    _normalize_iso_date(payload.get("date_contacted"), field_name="date_contacted")
    follow_up = payload.get("follow_up_date")
    if follow_up is not None and _text(follow_up):
        _normalize_iso_date(follow_up, field_name="follow_up_date")


def _row_from_payload(payload: dict[str, Any]) -> OutreachAttempt:
    validate_outreach_payload(payload, require_all=True)
    now = _now_utc_naive()
    return OutreachAttempt(
        person_name=_text(payload["person_name"]),
        company=_text(payload["company"]),
        designation=_optional_text(payload.get("designation")),
        linkedin_url=_optional_text(payload.get("linkedin_url")),
        outreach_channel=_text(payload["outreach_channel"]),
        outreach_message=_optional_text(payload.get("outreach_message")),
        ai_recommended_message=_optional_text(payload.get("ai_recommended_message")),
        date_contacted=_normalize_iso_date(
            payload["date_contacted"], field_name="date_contacted"
        )
        or "",
        follow_up_date=_normalize_iso_date(
            payload.get("follow_up_date"), field_name="follow_up_date"
        ),
        status=_text(payload.get("status") or "planned"),
        notes=_optional_text(payload.get("notes")),
        opportunity_id=_optional_text(payload.get("opportunity_id")),
        opportunity_url=_optional_text(payload.get("opportunity_url")),
        hiring_signal_type=_validate_hiring_signal_type(
            payload.get("hiring_signal_type"), required=True
        ),
        hiring_signal_url=_optional_text(payload.get("hiring_signal_url")),
        outreach_type=_optional_text(payload.get("outreach_type")),
        created_at=now,
        updated_at=now,
    )


def insert_outreach_attempt(payload: dict[str, Any]) -> int:
    if not dashboard_write_enabled():
        return 0
    ensure_database_ready()
    with get_session() as session:
        assert isinstance(session, Session)
        row = _row_from_payload(payload)
        session.add(row)
        session.flush()
        row_id = int(row.id)
        session.commit()
        return row_id


def _update_row_from_dict(existing: OutreachAttempt, row: dict[str, Any]) -> bool:
    changed = False
    for col in _EDITABLE_COLUMNS:
        if col not in row:
            continue
        if col in ("follow_up_date", "date_contacted"):
            new_value = _normalize_iso_date(row.get(col), field_name=col)
        elif col == "notes":
            new_value = _optional_text(row.get(col))
        elif col == "hiring_signal_url":
            new_value = _optional_text(row.get(col))
        elif col == "hiring_signal_type":
            new_value = _validate_hiring_signal_type(row.get(col), required=True)
        else:
            new_value = _text(row.get(col))
        current = getattr(existing, col)
        if current != new_value:
            setattr(existing, col, new_value)
            changed = True
    if changed:
        existing.updated_at = _now_utc_naive()
    return changed


def persist_outreach_table_edits(updated_rows: list[dict[str, Any]]) -> int:
    if not dashboard_write_enabled() or not updated_rows:
        return 0
    ensure_database_ready()
    count = 0
    with get_session() as session:
        assert isinstance(session, Session)
        for row in updated_rows:
            row_id = row.get("id")
            if row_id is None or str(row_id).strip() == "":
                continue
            existing = session.get(OutreachAttempt, int(row_id))
            if existing is None:
                continue
            if _update_row_from_dict(existing, row):
                count += 1
        session.commit()
    return count


def delete_outreach_attempt(row_id: int) -> bool:
    """Test helper only — not exposed in V1 UI."""
    if not dashboard_write_enabled():
        return False
    ensure_database_ready()
    with get_session() as session:
        assert isinstance(session, Session)
        existing = session.get(OutreachAttempt, int(row_id))
        if existing is None:
            return False
        session.delete(existing)
        session.commit()
        return True


def load_outreach_attempts_ordered(session: Session) -> list[OutreachAttempt]:
    rows = session.execute(
        select(OutreachAttempt).order_by(
            OutreachAttempt.follow_up_date.is_(None),
            OutreachAttempt.follow_up_date.asc(),
            OutreachAttempt.date_contacted.desc(),
        )
    ).scalars()
    return list(rows.all())
