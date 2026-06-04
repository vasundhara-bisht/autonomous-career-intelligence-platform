"""
Shared MAX_RUNS gating for acquisition sources.

Semantics:
  unset / empty env  -> use config_default
  positive integer N -> cap to N runs
  integer <= 0       -> hard disable (no scrape, no orchestration plan)
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class MaxRunsResolution:
    disabled: bool
    effective_max_runs: int
    env_var: str
    raw_value: str | None


def resolve_max_runs(
    env_var: str,
    *,
    config_default: int,
    source_label: str,
) -> MaxRunsResolution:
    """
    Resolve {SOURCE}_MAX_RUNS policy.

    Invalid non-integer values fall back to config_default (not disabled).
    """
    raw = os.environ.get(env_var, "").strip()
    default = max(1, int(config_default))

    if not raw:
        return MaxRunsResolution(
            disabled=False,
            effective_max_runs=default,
            env_var=env_var,
            raw_value=None,
        )

    try:
        parsed = int(raw)
    except ValueError:
        print(
            f"⚠️ {source_label}: invalid {env_var}={raw!r}; "
            f"using config default max_runs={default}"
        )
        return MaxRunsResolution(
            disabled=False,
            effective_max_runs=default,
            env_var=env_var,
            raw_value=raw,
        )

    if parsed <= 0:
        return MaxRunsResolution(
            disabled=True,
            effective_max_runs=0,
            env_var=env_var,
            raw_value=raw,
        )

    return MaxRunsResolution(
        disabled=False,
        effective_max_runs=parsed,
        env_var=env_var,
        raw_value=raw,
    )


def format_skip_message(resolution: MaxRunsResolution, source_label: str) -> str:
    shown = resolution.raw_value if resolution.raw_value is not None else "0"
    return f"⏭️ {source_label} disabled via {resolution.env_var}={shown}"


def effective_session_cap(requested: int | None, config_default: int) -> int:
    """Never treat 0 as falsy-unset; caller must hard-skip when cap is 0."""
    if requested is None:
        return max(1, int(config_default))
    return max(0, int(requested))
