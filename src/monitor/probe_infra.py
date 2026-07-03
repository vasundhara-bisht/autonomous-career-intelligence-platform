"""Shared probe infrastructure-error classification (auth probes)."""

from __future__ import annotations

PROBE_INFRASTRUCTURE_ERROR_PREFIXES: tuple[str, ...] = (
    "fetch:",
    "timeout:",
    "browser:",
    "runtime:",
    "sqlite:",
    "interrupted:",
)


def is_probe_infrastructure_error(error: object) -> bool:
    """Return True when a probe fetch error is infrastructure, not session/auth loss."""
    text = str(error or "").strip().lower()
    if not text:
        return False
    return any(text.startswith(prefix) for prefix in PROBE_INFRASTRUCTURE_ERROR_PREFIXES)
