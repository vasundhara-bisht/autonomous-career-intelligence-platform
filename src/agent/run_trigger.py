"""Run initiation trigger metadata (manual vs scheduled)."""

from __future__ import annotations

import os

ACQUISITION_RUN_TRIGGER_ENV = "ACQUISITION_RUN_TRIGGER"
LIFECYCLE_MONITOR_RUN_TRIGGER_ENV = "LIFECYCLE_MONITOR_RUN_TRIGGER"

RUN_TRIGGER_MANUAL = "manual"
RUN_TRIGGER_SCHEDULED = "scheduled"

_ALLOWED_TRIGGERS = frozenset({RUN_TRIGGER_MANUAL, RUN_TRIGGER_SCHEDULED})


def read_run_trigger(env_var: str) -> str | None:
    """Return manual or scheduled when env is set; otherwise None."""
    raw = os.environ.get(env_var, "").strip().lower()
    if raw in _ALLOWED_TRIGGERS:
        return raw
    return None
