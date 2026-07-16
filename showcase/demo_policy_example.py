"""Demo Policy example — illustrative excerpt, not the production module.

This is a trimmed version of the private repository's `src/demo/policy.py`:
a single source of truth for what Live vs Demo Mode is allowed to do. The
production version also gates CSV export mirrors; that piece depended on
removed persistence code and is omitted here to keep this example runnable
on its own, paired only with the kept `src/db/app_mode.py`.

Run from the repository root:

    PYTHONPATH=src python showcase/demo_policy_example.py
"""

from __future__ import annotations

import os

from db.app_mode import AppMode, get_active_mode, is_cloud_deployment


def automation_allowed() -> bool:
    """Schedulers, Run Now, Discovery execution, health monitors — denied in Demo."""
    return get_active_mode() is AppMode.LIVE


def external_api_allowed() -> bool:
    """LinkedIn/browser fetch, OpenAI regen — denied in Demo."""
    return get_active_mode() is AppMode.LIVE


def interactive_demo_writes_allowed() -> bool:
    """Product edits (jobs/CRM/outreach/catalog) are intentional in Demo."""
    return get_active_mode() is AppMode.DEMO


def operator_reset_allowed() -> bool:
    """Reset Demo DB is operator/CLI only — never anonymous Cloud UI."""
    if is_cloud_deployment():
        return False
    if os.environ.get("AI_JOB_AGENT_ALLOW_DEMO_RESET", "").strip().lower() in {
        "0",
        "false",
        "no",
        "off",
    }:
        return False
    return True


DEMO_UNAVAILABLE_HELP = (
    "Unavailable in Demo Mode — automation and external systems are disabled."
)


if __name__ == "__main__":
    for mode in (AppMode.LIVE, AppMode.DEMO):
        from db.app_mode import set_active_mode

        set_active_mode(mode)
        print(f"mode={mode.value}")
        print(f"  automation_allowed()             -> {automation_allowed()}")
        print(f"  external_api_allowed()           -> {external_api_allowed()}")
        print(f"  interactive_demo_writes_allowed() -> {interactive_demo_writes_allowed()}")
        print(f"  operator_reset_allowed()          -> {operator_reset_allowed()}")
