#!/usr/bin/env python3
"""Scheduler status JSON for dashboard Operational Controls (OHM Phase 5)."""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_SRC = _REPO_ROOT / "src"
for entry in (str(_REPO_ROOT), str(_SRC)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from agent.operator_scheduler import load_operator_scheduler_state  # noqa: E402
from agent.ohm_signoff import (  # noqa: E402
    is_lifecycle_resume_gated,
    lifecycle_resume_gate_reason,
    load_ohm_signoff_state,
)

ACQUISITION_LABEL = "com.vasundhara-bisht.ai-job-agent.acquisition"
LIFECYCLE_LABEL = "com.vasundhara-bisht.ai-job-agent.lifecycle-monitor"

_PLIST_TEMPLATES = {
    "acquisition": _REPO_ROOT
    / "scripts/scheduling/launchd/com.vasundhara-bisht.ai-job-agent.acquisition.plist.template",
    "lifecycle": _REPO_ROOT
    / "scripts/scheduling/launchd/com.vasundhara-bisht.ai-job-agent.lifecycle-monitor.plist.template",
}


def _format_schedule_label(hour: int, minute: int) -> str:
    return f"{hour:02d}:{minute:02d}"


def _parse_plist_schedule(plist_path: Path) -> list[str]:
    if not plist_path.exists():
        return []
    text = plist_path.read_text(encoding="utf-8")
    hours = [int(value) for value in re.findall(r"<key>Hour</key>\s*<integer>(\d+)</integer>", text)]
    minutes = [
        int(value) for value in re.findall(r"<key>Minute</key>\s*<integer>(\d+)</integer>", text)
    ]
    return [
        _format_schedule_label(hour, minute)
        for hour, minute in zip(hours, minutes, strict=False)
    ]


def _schedule_summary(scheduler: str, repo_root: Path | None = None) -> str:
    root = repo_root or _REPO_ROOT
    template = root / "scripts/scheduling/launchd"
    if scheduler == "acquisition":
        plist = template / "com.vasundhara-bisht.ai-job-agent.acquisition.plist.template"
        labels = _parse_plist_schedule(plist)
        if not labels:
            return "~09:00, 21:00 daily"
        return f"~{', '.join(labels)} daily"
    plist = template / "com.vasundhara-bisht.ai-job-agent.lifecycle-monitor.plist.template"
    labels = _parse_plist_schedule(plist)
    if not labels:
        return "~17:00 daily"
    return f"~{labels[0]} daily"


def _launchctl_domain() -> str:
    uid = os.getuid()
    return f"gui/{uid}"


def _launchctl_print(label: str) -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            ["launchctl", "print", f"{_launchctl_domain()}/{label}"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    output = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode == 0, output.strip()


def _parse_launchctl_state(output: str) -> str:
    for line in output.splitlines():
        stripped = line.strip()
        if stripped.startswith("state ="):
            return stripped.split("=", 1)[1].strip()
        if stripped.startswith("pid ="):
            pid = stripped.split("=", 1)[1].strip()
            if pid and pid != "0":
                return "running"
    if "Could not find service" in output or "No such process" in output:
        return "not_loaded"
    return "unknown"


def _installed_plist_path(label: str) -> Path | None:
    candidate = Path.home() / "Library/LaunchAgents" / f"{label}.plist"
    return candidate if candidate.exists() else None


def read_scheduler_entry(
    scheduler: str,
    *,
    label: str,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    loaded, output = _launchctl_print(label)
    installed = _installed_plist_path(label)
    pause_state = load_operator_scheduler_state()
    pause_key = f"{scheduler}_paused"
    return {
        "scheduler": scheduler,
        "label": label,
        "platform": platform.system().lower(),
        "launchctl_loaded": loaded,
        "launchctl_state": _parse_launchctl_state(output) if loaded else "not_loaded",
        "plist_installed": installed is not None,
        "plist_path": str(installed) if installed else None,
        "next_run_estimate": _schedule_summary(scheduler, repo_root=repo_root),
        "operator_paused": bool(pause_state.get(pause_key, False)),
        "launchctl_output_excerpt": output[:500] if output else "",
    }


def read_scheduler_status(*, repo_root: Path | None = None) -> dict[str, Any]:
    """Return scheduler status for acquisition and lifecycle monitor."""
    root = repo_root or _REPO_ROOT
    pause_state = load_operator_scheduler_state()
    signoff = load_ohm_signoff_state()
    gated = is_lifecycle_resume_gated()
    return {
        "platform": platform.system().lower(),
        "darwin": platform.system().lower() == "darwin",
        "operator_scheduler": pause_state,
        "ohm_signoff": signoff,
        "lifecycle_resume_gated": gated,
        "lifecycle_resume_gate_reason": lifecycle_resume_gate_reason() if gated else "",
        "schedulers": {
            "acquisition": read_scheduler_entry(
                "acquisition",
                label=ACQUISITION_LABEL,
                repo_root=root,
            ),
            "lifecycle": read_scheduler_entry(
                "lifecycle",
                label=LIFECYCLE_LABEL,
                repo_root=root,
            ),
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Print scheduler status JSON.")
    parser.add_argument(
        "--repo-root",
        default=str(_REPO_ROOT),
        help="Repository root for plist template resolution.",
    )
    args = parser.parse_args(argv)
    payload = read_scheduler_status(repo_root=Path(args.repo_root))
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
