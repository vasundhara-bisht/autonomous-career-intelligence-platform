"""Operator scheduler pause flags (OHM Phase 5 soft pause)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import paths

_OPERATOR_SCHEDULER_FILENAME = "operator_scheduler.json"


def operator_scheduler_path() -> Path:
    return paths.ensure_data_dir() / _OPERATOR_SCHEDULER_FILENAME


def _default_state() -> dict[str, Any]:
    return {
        "lifecycle_paused": False,
        "acquisition_paused": False,
    }


def load_operator_scheduler_state(path: Path | None = None) -> dict[str, Any]:
    """Load pause flags from data/operator_scheduler.json."""
    target = path or operator_scheduler_path()
    if not target.exists():
        return _default_state()
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _default_state()
    if not isinstance(raw, dict):
        return _default_state()
    state = _default_state()
    state["lifecycle_paused"] = bool(raw.get("lifecycle_paused", False))
    state["acquisition_paused"] = bool(raw.get("acquisition_paused", False))
    return state


def save_operator_scheduler_state(
    state: dict[str, Any],
    *,
    path: Path | None = None,
) -> None:
    """Persist pause flags to data/operator_scheduler.json."""
    target = path or operator_scheduler_path()
    paths.ensure_data_dir()
    payload = {
        "lifecycle_paused": bool(state.get("lifecycle_paused", False)),
        "acquisition_paused": bool(state.get("acquisition_paused", False)),
    }
    target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def is_scheduler_paused(scheduler: str, *, path: Path | None = None) -> bool:
    """Return True when acquisition or lifecycle scheduler is soft-paused."""
    key = f"{(scheduler or '').strip().lower()}_paused"
    if key not in {"acquisition_paused", "lifecycle_paused"}:
        raise ValueError(f"unknown scheduler: {scheduler!r}")
    state = load_operator_scheduler_state(path)
    return bool(state.get(key, False))


def set_scheduler_paused(scheduler: str, paused: bool, *, path: Path | None = None) -> dict[str, Any]:
    """Update soft-pause flag for acquisition or lifecycle."""
    normalized = (scheduler or "").strip().lower()
    state = load_operator_scheduler_state(path)
    if normalized == "acquisition":
        state["acquisition_paused"] = bool(paused)
    elif normalized == "lifecycle":
        state["lifecycle_paused"] = bool(paused)
    else:
        raise ValueError(f"unknown scheduler: {scheduler!r}")
    save_operator_scheduler_state(state, path=path)
    return state
