"""Application mode: Live vs Demo product-memory routing.

Portfolio excerpt — kept as a small, self-contained example of mode-gated
design. Paired with showcase/demo_policy_example.py.
"""

from __future__ import annotations

import os
from contextvars import ContextVar
from enum import Enum


class AppMode(str, Enum):
    LIVE = "live"
    DEMO = "demo"


_ACTIVE_MODE: ContextVar[AppMode] = ContextVar("app_mode", default=AppMode.LIVE)


def get_active_mode() -> AppMode:
    return _ACTIVE_MODE.get()


def set_active_mode(mode: AppMode | str) -> AppMode:
    if isinstance(mode, AppMode):
        resolved = mode
    else:
        resolved = AppMode(str(mode).strip().lower())
    _ACTIVE_MODE.set(resolved)
    return resolved


def is_demo_mode() -> bool:
    return get_active_mode() is AppMode.DEMO


def is_cloud_deployment() -> bool:
    """Heuristic for Streamlit Community Cloud / public deploy."""
    explicit = os.environ.get("AI_JOB_AGENT_DEPLOYMENT", "").strip().lower()
    if explicit in {"cloud", "community_cloud", "streamlit_cloud"}:
        return True
    if explicit in {"local", "operator", "dev"}:
        return False
    # Streamlit Cloud commonly sets these.
    if os.environ.get("ST_COMMUNITY_CLOUD", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return True
    if os.environ.get("STREAMLIT_SHARING_MODE", "").strip():
        return True
    if os.environ.get("STREAMLIT_SERVER_HEADLESS", "").strip().lower() in {
        "true",
        "1",
    } and os.environ.get("HOSTNAME", "").endswith(".streamlit.app"):
        return True
    return False


def mode_switch_allowed() -> bool:
    """Live/Demo toggle is disabled on Streamlit Community Cloud (Demo-only)."""
    return not is_cloud_deployment()


def resolve_default_app_mode() -> AppMode:
    """
    Configurable default mode.

    Prefer AI_JOB_AGENT_DEFAULT_APP_MODE=live|demo.
    If unset: Demo on Cloud/public deploy, Live for local/operator.
    """
    raw = os.environ.get("AI_JOB_AGENT_DEFAULT_APP_MODE", "").strip().lower()
    if raw in {AppMode.LIVE.value, AppMode.DEMO.value}:
        return AppMode(raw)
    if is_cloud_deployment():
        return AppMode.DEMO
    return AppMode.LIVE
