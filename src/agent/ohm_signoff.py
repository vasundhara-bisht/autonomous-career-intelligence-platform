"""OHM Phase 6 operator sign-off state (lifecycle re-enable gate)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import paths

_OHM_SIGNOFF_FILENAME = "ohm_signoff.json"


def ohm_signoff_path() -> Path:
    return paths.ensure_data_dir() / _OHM_SIGNOFF_FILENAME


def _default_state() -> dict[str, Any]:
    return {
        "validation_ladder_passed": False,
        "validation_ladder_recorded_at": None,
        "lifecycle_resume_approved": False,
        "approved_at": None,
        "approved_by": None,
        "notes": "",
    }


def load_ohm_signoff_state(path: Path | None = None) -> dict[str, Any]:
    """Load OHM Phase 6 sign-off flags from data/ohm_signoff.json."""
    target = path or ohm_signoff_path()
    if not target.exists():
        return _default_state()
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _default_state()
    if not isinstance(raw, dict):
        return _default_state()
    state = _default_state()
    state["validation_ladder_passed"] = bool(raw.get("validation_ladder_passed", False))
    state["validation_ladder_recorded_at"] = raw.get("validation_ladder_recorded_at")
    state["lifecycle_resume_approved"] = bool(raw.get("lifecycle_resume_approved", False))
    state["approved_at"] = raw.get("approved_at")
    state["approved_by"] = str(raw.get("approved_by") or "").strip() or None
    state["notes"] = str(raw.get("notes") or "").strip()
    return state


def save_ohm_signoff_state(state: dict[str, Any], *, path: Path | None = None) -> None:
    """Persist OHM sign-off flags."""
    target = path or ohm_signoff_path()
    paths.ensure_data_dir()
    payload = {
        "validation_ladder_passed": bool(state.get("validation_ladder_passed", False)),
        "validation_ladder_recorded_at": state.get("validation_ladder_recorded_at"),
        "lifecycle_resume_approved": bool(state.get("lifecycle_resume_approved", False)),
        "approved_at": state.get("approved_at"),
        "approved_by": str(state.get("approved_by") or "").strip() or None,
        "notes": str(state.get("notes") or "").strip(),
    }
    target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def is_lifecycle_resume_gated(*, path: Path | None = None) -> bool:
    """Return True until operator records Phase 6 lifecycle resume approval."""
    return not bool(load_ohm_signoff_state(path).get("lifecycle_resume_approved"))


def lifecycle_resume_gate_reason(*, path: Path | None = None) -> str:
    state = load_ohm_signoff_state(path)
    if state.get("lifecycle_resume_approved"):
        return ""
    if not state.get("validation_ladder_passed"):
        return (
            "Complete the OHM Phase 6 validation ladder and record sign-off before "
            "re-enabling the lifecycle LaunchAgent."
        )
    return (
        "Record explicit OHM Phase 6 operator approval before re-enabling the "
        "lifecycle LaunchAgent."
    )


def record_validation_ladder_passed(*, notes: str = "", path: Path | None = None) -> dict[str, Any]:
    """Mark automated validation ladder as passed (operator step after script run)."""
    state = load_ohm_signoff_state(path)
    state["validation_ladder_passed"] = True
    state["validation_ladder_recorded_at"] = datetime.now(UTC).replace(tzinfo=None).isoformat(
        timespec="seconds"
    )
    if notes.strip():
        state["notes"] = notes.strip()
    save_ohm_signoff_state(state, path=path)
    return state


def approve_lifecycle_resume(
    *,
    approved_by: str,
    notes: str = "",
    path: Path | None = None,
) -> dict[str, Any]:
    """Record explicit operator approval to re-enable lifecycle scheduling."""
    operator = str(approved_by or "").strip()
    if not operator:
        raise ValueError("approved_by is required")
    state = load_ohm_signoff_state(path)
    state["lifecycle_resume_approved"] = True
    state["approved_at"] = datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds")
    state["approved_by"] = operator
    if notes.strip():
        state["notes"] = notes.strip()
    save_ohm_signoff_state(state, path=path)
    return state
