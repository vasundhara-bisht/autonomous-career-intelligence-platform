"""Operational Controls dashboard section (OHM Phase 5)."""

from __future__ import annotations

import html
import os
import platform
import re
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import streamlit as st

from db.read.engine import dashboard_read_enabled, dashboard_write_enabled
from monitor_display import present_run_status
from monitor_ui import (
    acquisition_poll_wake_active,
    format_monitor_timestamp,
    lifecycle_poll_wake_active,
    mark_acquisition_poll_wake,
    mark_lifecycle_poll_wake,
    monitor_db_running,
)
from ui_help import help_icon_html, inject_dashboard_help_css, normalize_section_title

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCHEDULER_STATUS_SCRIPT = _REPO_ROOT / "scripts/scheduling/read_scheduler_status.py"
_RUN_CONFIRM_STATE_PREFIX = "op_run_confirm_"
_AI_REFRESH_LOCK = "/tmp/ai-job-agent-ai-refresh.lock"
_AI_REFRESH_POLLING_KEY = "op_ai_refresh_polling"
_ACQUISITION_LOCK = os.environ.get(
    "AI_JOB_AGENT_LOCK_FILE", "/tmp/ai-job-agent-acquisition.lock"
)
_LIFECYCLE_LOCK = os.environ.get(
    "AI_JOB_AGENT_LIFECYCLE_LOCK_FILE", "/tmp/ai-job-agent-lifecycle-monitor.lock"
)
_OP_OPERATOR_HAD_EXECUTION_KEY = "op_operator_had_execution"

_OPERATOR_CONTROLS_CSS = """
<style>
.dash-section-header.op-controls-section-header {
    margin: 0 !important;
}
div[data-testid="element-container"]:has(hr) + div[data-testid="element-container"]:has(.op-controls-section-header) {
    margin-top: -0.35rem !important;
}
div[data-testid="element-container"]:has(.op-controls-section-header) {
    margin-bottom: -1.55rem !important;
    padding-bottom: 0 !important;
}
.op-controls-cards-anchor {
    display: block;
    height: 0;
    margin: 0;
    padding: 0;
    line-height: 0;
    font-size: 0;
    overflow: hidden;
}
div[data-testid="element-container"]:has(.op-controls-cards-anchor) {
    margin-top: -1.15rem !important;
    margin-bottom: -0.85rem !important;
    padding: 0 !important;
    min-height: 0 !important;
}
[data-testid="stVerticalBlockBorderWrapper"]:has(.op-card-title) {
    padding: 0.65rem 0.85rem 0.75rem;
}
.op-card-title {
    font-size: 0.98rem;
    font-weight: 650;
    line-height: 1.25;
    color: rgb(49, 51, 63);
    margin: 0 0 0.55rem 0;
}
.op-card-row {
    display: flex;
    align-items: center;
    gap: 0.45rem;
    margin: 0 0 0.3rem 0;
    font-size: 0.82rem;
    line-height: 1.35;
    color: rgba(49, 51, 63, 0.78);
}
.op-card-row .op-row-label {
    min-width: 7.25rem;
    font-weight: 500;
    color: rgba(49, 51, 63, 0.62);
}
.op-card-row .op-row-value {
    color: rgb(49, 51, 63);
    font-weight: 500;
}
.op-status-badge {
    display: inline-flex;
    align-items: center;
    padding: 0.12rem 0.5rem;
    border-radius: 999px;
    font-size: 0.74rem;
    font-weight: 600;
    line-height: 1.2;
    letter-spacing: 0.01em;
    white-space: nowrap;
}
.op-status-green {
    color: rgb(27, 94, 32);
    background: rgba(46, 125, 50, 0.14);
    border: 1px solid rgba(46, 125, 50, 0.28);
}
.op-status-yellow {
    color: rgb(130, 90, 0);
    background: rgba(200, 145, 0, 0.14);
    border: 1px solid rgba(200, 145, 0, 0.28);
}
.op-status-red {
    color: rgb(183, 28, 28);
    background: rgba(211, 47, 47, 0.12);
    border: 1px solid rgba(211, 47, 47, 0.28);
}
.op-status-grey {
    color: rgba(49, 51, 63, 0.78);
    background: rgba(128, 128, 128, 0.12);
    border: 1px solid rgba(128, 128, 128, 0.22);
}
.op-lock-hint-row {
    margin-top: 0.15rem;
    min-height: 0;
}
.op-override-row {
    display: flex;
    align-items: center;
    gap: 0.4rem;
    margin: 0.35rem 0 0.85rem 0;
    font-size: 0.8rem;
    color: rgba(49, 51, 63, 0.72);
}
.op-override-row .op-row-label {
    font-weight: 500;
}
.op-lock-hint {
    display: flex;
    align-items: flex-start;
    gap: 0.3rem;
    margin-top: 0.2rem;
    font-size: 0.74rem;
    line-height: 1.35;
    color: rgba(49, 51, 63, 0.62);
}
.op-lock-hint .op-lock-icon {
    flex-shrink: 0;
    font-size: 0.78rem;
    line-height: 1.35;
}
[data-testid="stVerticalBlockBorderWrapper"]:has(.op-card-title) [data-testid="stButton"] > button {
    width: 100%;
    min-height: 2.1rem;
    border-radius: 0.45rem !important;
    border: 1px solid rgba(49, 51, 63, 0.22) !important;
    background: rgb(255, 255, 255) !important;
    color: rgb(49, 51, 63) !important;
    font-size: 0.82rem !important;
    font-weight: 600 !important;
    box-shadow: 0 1px 2px rgba(0, 0, 0, 0.04);
}
[data-testid="stVerticalBlockBorderWrapper"]:has(.op-card-title)
  [data-testid="stHorizontalBlock"]:has([data-testid="stButton"])
  > [data-testid="column"]:nth-child(3) [data-testid="stButton"] > button {
    min-height: 2.1rem !important;
    font-size: 0.76rem !important;
    background: rgba(123, 104, 238, 0.06) !important;
    border: 1.5px solid rgba(94, 72, 214, 0.55) !important;
    color: rgb(94, 72, 214) !important;
    box-shadow: none;
}
[data-testid="stVerticalBlockBorderWrapper"]:has(.op-card-title)
  [data-testid="stHorizontalBlock"]:has([data-testid="stButton"])
  > [data-testid="column"]:nth-child(3) [data-testid="stButton"] > button:hover:not(:disabled) {
    background: rgba(123, 104, 238, 0.12) !important;
    border-color: rgba(94, 72, 214, 0.75) !important;
    color: rgb(76, 56, 196) !important;
}
[data-testid="stVerticalBlockBorderWrapper"]:has(.op-card-title)
  [data-testid="stHorizontalBlock"]:has([data-testid="stButton"])
  > [data-testid="column"]:nth-child(3) [data-testid="stButton"] > button:disabled {
    background: rgba(123, 104, 238, 0.04) !important;
    border-style: dashed !important;
    border-color: rgba(94, 72, 214, 0.28) !important;
    color: rgba(94, 72, 214, 0.42) !important;
}
[data-testid="stVerticalBlockBorderWrapper"]:has(.op-card-title) [data-testid="stButton"] > button:hover:not(:disabled) {
    border-color: rgba(49, 51, 63, 0.38) !important;
    background: rgba(240, 242, 246, 0.95) !important;
}
[data-testid="stVerticalBlockBorderWrapper"]:has(.op-card-title) [data-testid="stButton"] > button:disabled {
    opacity: 1 !important;
    border-style: dashed !important;
    border-color: rgba(49, 51, 63, 0.18) !important;
    background: rgba(250, 250, 250, 0.95) !important;
    color: rgba(49, 51, 63, 0.42) !important;
    box-shadow: none;
}
.op-run-confirm-panel {
    margin-top: 0.55rem;
    padding: 0.65rem 0.75rem;
    border-radius: 0.45rem;
    border: 1px solid rgba(94, 72, 214, 0.28);
    background: rgba(123, 104, 238, 0.06);
}
.op-run-confirm-title {
    font-size: 0.88rem;
    font-weight: 650;
    color: rgb(49, 51, 63);
    margin: 0 0 0.25rem 0;
}
.op-run-confirm-body {
    font-size: 0.78rem;
    line-height: 1.4;
    color: rgba(49, 51, 63, 0.72);
    margin: 0 0 0.55rem 0;
}
.op-ai-refresh-preview-card {
    margin: 0.55rem 0 0.7rem 0;
    padding: 0.7rem 0.85rem;
    border-radius: 0.5rem;
    border: 1px solid rgba(94, 72, 214, 0.22);
    background: linear-gradient(
        180deg,
        rgba(123, 104, 238, 0.08) 0%,
        rgba(123, 104, 238, 0.03) 100%
    );
}
.op-ai-refresh-preview-title {
    font-size: 0.8rem;
    font-weight: 650;
    color: rgb(76, 56, 196);
    margin: 0 0 0.55rem 0;
}
.op-ai-refresh-preview-stat {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    gap: 0.75rem;
    margin: 0 0 0.35rem 0;
    font-size: 0.8rem;
    line-height: 1.35;
}
.op-ai-refresh-preview-stat:last-child {
    margin-bottom: 0;
}
.op-ai-refresh-preview-label {
    color: rgba(49, 51, 63, 0.68);
    font-weight: 500;
}
.op-ai-refresh-preview-value {
    color: rgb(94, 72, 214);
    font-weight: 700;
    font-size: 0.9rem;
    text-align: right;
}
.op-readonly-note {
    font-size: 0.8rem;
    color: rgba(49, 51, 63, 0.72);
    line-height: 1.45;
    margin: 0 0 0.5rem 0;
}
.op-readonly-note strong {
    color: rgb(49, 51, 63);
}
</style>
"""


def _inject_operator_controls_css() -> None:
    inject_dashboard_help_css()
    st.markdown(_OPERATOR_CONTROLS_CSS, unsafe_allow_html=True)


def _render_operational_controls_heading(*help_lines: str) -> None:
    inject_dashboard_help_css()
    display_title = normalize_section_title("Operational Controls")
    st.markdown(
        '<div class="dash-section-header op-controls-section-header">'
        f'<span class="dash-section-header-text">{html.escape(display_title)}</span>'
        f"{help_icon_html(*help_lines)}"
        "</div>",
        unsafe_allow_html=True,
    )


def _load_scheduler_status() -> dict[str, object]:
    if not _SCHEDULER_STATUS_SCRIPT.exists():
        return {}
    try:
        proc = subprocess.run(
            [sys.executable, str(_SCHEDULER_STATUS_SCRIPT)],
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
            cwd=str(_REPO_ROOT),
        )
    except (OSError, subprocess.TimeoutExpired):
        return {}
    if proc.returncode != 0 or not proc.stdout.strip():
        return {}
    import json

    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _format_next_scheduled_run(estimate: object) -> str:
    """Present backend schedule estimate without template wording."""
    raw = str(estimate or "").strip().lstrip("~")
    if not raw or raw == "—":
        return "—"
    if not raw.endswith(" daily"):
        return raw
    times_part = raw[: -len(" daily")].strip()
    times = [part.strip() for part in times_part.split(",") if part.strip()]
    if not times:
        return "—"
    if len(times) == 1:
        return f"{_friendly_clock_time(times[0])} daily"
    return f"{' & '.join(times)} daily"


def _friendly_clock_time(value: str) -> str:
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", value.strip())
    if not match:
        return value
    hour = int(match.group(1))
    minute = int(match.group(2))
    if hour == 0:
        return f"12:{minute:02d} AM"
    if hour < 12:
        return f"{hour}:{minute:02d} AM"
    if hour == 12:
        return f"12:{minute:02d} PM"
    return f"{hour - 12}:{minute:02d} PM"


def _scheduler_status_badge(entry: dict[str, object] | None) -> tuple[str, str]:
    """Scheduler / LaunchAgent state only (not pipeline execution)."""
    if not entry:
        return "Unavailable", "red"
    if entry.get("operator_paused"):
        return "Paused by operator", "yellow"
    if not entry.get("plist_installed"):
        return "Not installed", "red"
    state = str(entry.get("launchctl_state") or "").strip().lower()
    if state == "not_loaded":
        return "Not loaded", "red"
    if state == "not_installed":
        return "Not installed", "red"
    return "Scheduled", "green"


def _execution_status_badge(*, running: bool) -> tuple[str, str]:
    if running:
        return "Running", "green"
    return "Idle", "grey"


def _file_lock_held(path: str) -> bool:
    if not os.path.isfile(path):
        return False
    try:
        import fcntl

        with open(path, "a+", encoding="utf-8") as fp:
            try:
                fcntl.flock(fp.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(fp.fileno(), fcntl.LOCK_UN)
                return False
            except BlockingIOError:
                return True
    except OSError:
        return False


def _acquisition_is_executing() -> bool:
    return _file_lock_held(_ACQUISITION_LOCK)


def _lifecycle_is_executing() -> bool:
    return monitor_db_running() or _file_lock_held(_LIFECYCLE_LOCK)


def _scheduler_is_executing(scheduler_key: str) -> bool:
    if scheduler_key == "acquisition":
        return _acquisition_is_executing()
    if scheduler_key == "lifecycle":
        return _lifecycle_is_executing()
    return False


def _operator_execution_active() -> bool:
    return _acquisition_is_executing() or _lifecycle_is_executing()


def _operator_execution_poll_needed() -> bool:
    return (
        _operator_execution_active()
        or acquisition_poll_wake_active()
        or lifecycle_poll_wake_active()
    )


def _scheduler_badge(entry: dict[str, object] | None) -> tuple[str, str]:
    """Backward-compatible alias for scheduler status badge."""
    return _scheduler_status_badge(entry)


def _status_badge_html(label: str, tone: str) -> str:
    safe_label = html.escape(label)
    safe_tone = html.escape(tone)
    return (
        f'<span class="op-status-badge op-status-{safe_tone}">{safe_label}</span>'
    )


def _card_meta_row(label: str, value_html: str) -> str:
    return (
        '<div class="op-card-row">'
        f'<span class="op-row-label">{html.escape(label)}</span>'
        f'<span class="op-row-value">{value_html}</span>'
        "</div>"
    )


def _operator_override_label(acquisition_paused: bool, lifecycle_paused: bool) -> str:
    if acquisition_paused or lifecycle_paused:
        parts: list[str] = []
        if acquisition_paused:
            parts.append("Acquisition")
        if lifecycle_paused:
            parts.append("Lifecycle")
        return f"Yes ({', '.join(parts)})"
    return "No"


def _lifecycle_resume_hint(gate_reason: object) -> str:
    text = str(gate_reason or "").strip()
    if not text:
        return "Resume locked until Phase 6 sign-off."
    if "phase 6" in text.lower():
        return "Resume locked until Phase 6 sign-off."
    return text


def _set_scheduler_paused(scheduler: str, paused: bool) -> None:
    from agent.operator_scheduler import set_scheduler_paused

    set_scheduler_paused(scheduler, paused)


def _install_lifecycle_launchagent() -> tuple[bool, str]:
    script = _REPO_ROOT / "scripts/scheduling/install_launchagents.sh"
    if not script.exists():
        return False, f"install script not found: {script}"
    try:
        proc = subprocess.run(
            [str(script), "--lifecycle-only"],
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
            cwd=str(_REPO_ROOT),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    output = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode != 0:
        return False, output.strip() or f"install exit={proc.returncode}"
    return True, output.strip() or "Lifecycle LaunchAgent installed."


def _resume_lifecycle_scheduler() -> tuple[bool, str]:
    ok, message = _install_lifecycle_launchagent()
    if not ok:
        return False, message
    _set_scheduler_paused("lifecycle", False)
    return True, f"{message} Soft pause cleared."


_MANUAL_RUN_SCRIPTS = {
    "acquisition": _REPO_ROOT / "scripts" / "scheduling" / "run_manual_acquisition.sh",
    "lifecycle": _REPO_ROOT / "scripts" / "scheduling" / "run_manual_lifecycle_monitor.sh",
}


def _manual_run_log_path(scheduler_key: str) -> Path:
    log_dir = _REPO_ROOT / "logs" / "manual"
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    if scheduler_key == "acquisition":
        return log_dir / f"acquisition-{stamp}.log"
    return log_dir / f"lifecycle-monitor-{stamp}.log"


def _execute_manual_run(*, scheduler_key: str, title: str) -> tuple[bool, str]:
    script = _MANUAL_RUN_SCRIPTS.get(scheduler_key)
    if script is None:
        return False, f"unknown scheduler: {scheduler_key}"
    if not script.is_file():
        return False, f"Manual run script not found: {script}"
    log_path = _manual_run_log_path(scheduler_key)
    env = os.environ.copy()
    if scheduler_key == "acquisition":
        env["ACQUISITION_RUN_LOG_FILE"] = str(log_path)
    else:
        env["LIFECYCLE_MONITOR_LOG_FILE"] = str(log_path)
    try:
        subprocess.Popen(
            ["bash", str(script)],
            cwd=str(_REPO_ROOT),
            env=env,
            start_new_session=True,
        )
    except OSError as exc:
        return False, str(exc)
    return True, f"Started {title.lower()} in background. Log: {log_path}"


def _run_confirmation_title(title: str) -> str:
    return f"Run {title.lower()} now?"


def _run_confirmation_body(title: str) -> str:
    if title == "Acquisition":
        return (
            "This will immediately start a manual acquisition run. "
            "Operator pause does not block this action; scheduled 09:00 and 21:00 runs "
            "remain paused until you resume."
        )
    return (
        "This will immediately start a manual lifecycle monitor run. "
        "Operator pause does not block this action; the scheduled 17:00 run "
        "remains paused until you resume."
    )


def _run_confirm_state_key(scheduler_key: str) -> str:
    return f"{_RUN_CONFIRM_STATE_PREFIX}{scheduler_key}"


def _dialog_supported() -> bool:
    return hasattr(st, "dialog")


def _execute_run_now(*, scheduler_key: str, title: str) -> None:
    ok, message = _execute_manual_run(scheduler_key=scheduler_key, title=title)
    if ok:
        if scheduler_key == "lifecycle":
            mark_lifecycle_poll_wake()
        elif scheduler_key == "acquisition":
            mark_acquisition_poll_wake()
        st.success(message)
    else:
        st.error(message)


def _open_run_confirmation_dialog(
    *,
    scheduler_key: str,
    title: str,
) -> None:
    dialog_title = _run_confirmation_title(title)
    body = _run_confirmation_body(title)

    @st.dialog(dialog_title)
    def _dialog() -> None:
        st.markdown(body)
        cancel_col, confirm_col = st.columns(2)
        with cancel_col:
            if st.button("Cancel", key=f"dialog_cancel_{scheduler_key}", use_container_width=True):
                st.rerun()
        with confirm_col:
            if st.button(
                "Run now",
                key=f"dialog_confirm_{scheduler_key}",
                type="primary",
                use_container_width=True,
            ):
                _execute_run_now(scheduler_key=scheduler_key, title=title)
                st.rerun()

    _dialog()


def _request_inline_run_confirmation(scheduler_key: str) -> None:
    st.session_state[_run_confirm_state_key(scheduler_key)] = True


def _clear_inline_run_confirmation(scheduler_key: str) -> None:
    st.session_state.pop(_run_confirm_state_key(scheduler_key), None)


def _render_inline_run_confirmation(
    *,
    scheduler_key: str,
    title: str,
) -> None:
    if not st.session_state.get(_run_confirm_state_key(scheduler_key)):
        return
    st.markdown(
        '<div class="op-run-confirm-panel">'
        f'<p class="op-run-confirm-title">{html.escape(_run_confirmation_title(title))}</p>'
        f'<p class="op-run-confirm-body">{html.escape(_run_confirmation_body(title))}</p>'
        "</div>",
        unsafe_allow_html=True,
    )
    cancel_col, confirm_col = st.columns(2)
    with cancel_col:
        if st.button("Cancel", key=f"inline_cancel_{scheduler_key}", use_container_width=True):
            _clear_inline_run_confirmation(scheduler_key)
            st.rerun()
    with confirm_col:
        if st.button(
            "Run now",
            key=f"inline_confirm_{scheduler_key}",
            type="primary",
            use_container_width=True,
        ):
            _clear_inline_run_confirmation(scheduler_key)
            _execute_run_now(scheduler_key=scheduler_key, title=title)
            st.rerun()


def _handle_run_now_click(
    *,
    scheduler_key: str,
    title: str,
) -> None:
    if _dialog_supported():
        _open_run_confirmation_dialog(
            scheduler_key=scheduler_key,
            title=title,
        )
        return
    _request_inline_run_confirmation(scheduler_key)
    st.rerun()


def _open_lifecycle_approve_dialog() -> None:
    @st.dialog("Approve lifecycle re-enable")
    def _dialog() -> None:
        st.markdown(
            "Record explicit OHM Phase 6 operator approval. "
            "This ungates the lifecycle **Resume** control for LaunchAgent installation."
        )
        operator = st.text_input("Operator name", key="ohm_operator_name_input")
        notes = st.text_area("Notes (optional)", key="ohm_operator_notes_input")
        cancel_col, approve_col = st.columns(2)
        with cancel_col:
            if st.button("Cancel", key="ohm_approve_cancel", use_container_width=True):
                st.session_state.pop("ohm_approve_dialog_open", None)
                st.rerun()
        with approve_col:
            if st.button("Approve", key="ohm_approve_confirm", type="primary", use_container_width=True):
                from agent.ohm_signoff import approve_lifecycle_resume

                name = str(operator or "").strip()
                if not name:
                    st.error("Operator name is required.")
                    return
                approve_lifecycle_resume(approved_by=name, notes=str(notes or ""))
                st.session_state.pop("ohm_approve_dialog_open", None)
                st.success("Lifecycle re-enable approved.")
                st.rerun()

    _dialog()


def _open_lifecycle_resume_dialog() -> None:
    @st.dialog("Re-enable lifecycle monitor?")
    def _dialog() -> None:
        st.markdown(
            "This installs/reloads the lifecycle LaunchAgent (17:00 IST once daily) "
            "and clears any operator soft pause. Scheduled acquisition runs are not affected."
        )
        cancel_col, confirm_col = st.columns(2)
        with cancel_col:
            if st.button("Cancel", key="lifecycle_resume_cancel", use_container_width=True):
                st.rerun()
        with confirm_col:
            if st.button("Re-enable", key="lifecycle_resume_confirm", type="primary", use_container_width=True):
                ok, message = _resume_lifecycle_scheduler()
                if ok:
                    st.success(f"Lifecycle monitor re-enabled. {message}")
                else:
                    st.error(message)
                st.rerun()

    _dialog()


def _ai_refresh_lock_held() -> bool:
    if not os.path.isfile(_AI_REFRESH_LOCK):
        return False
    try:
        import fcntl

        with open(_AI_REFRESH_LOCK, "a+", encoding="utf-8") as fp:
            try:
                fcntl.flock(fp.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(fp.fileno(), fcntl.LOCK_UN)
                return False
            except BlockingIOError:
                return True
    except OSError:
        return False


def _ai_refresh_db_running() -> bool:
    if not dashboard_read_enabled():
        return False
    try:
        from sqlalchemy import text

        from db.bootstrap import ensure_database_ready
        from db.read.engine import get_dashboard_read_session

        ensure_database_ready()
        with get_dashboard_read_session() as session:
            row = session.execute(
                text(
                    "SELECT 1 FROM ai_refresh_runs WHERE status = 'running' LIMIT 1"
                )
            ).first()
            return row is not None
    except Exception:
        return False


def _ai_refresh_is_running() -> bool:
    return _ai_refresh_lock_held() or _ai_refresh_db_running()


def _ai_refresh_status_badge(running: bool) -> tuple[str, str]:
    if running:
        return "Running", "green"
    return "Not Running", "grey"


def _mark_ai_refresh_polling_started() -> None:
    st.session_state[_AI_REFRESH_POLLING_KEY] = True


def _ai_refresh_python() -> str:
    venv_python = _REPO_ROOT / "venv" / "bin" / "python"
    if venv_python.is_file():
        return str(venv_python)
    return sys.executable


def _load_ai_refresh_last_run() -> dict[str, object] | None:
    if not dashboard_read_enabled():
        return None
    try:
        from db.bootstrap import ensure_database_ready
        from db.read.ai_refresh_runs import load_latest_ai_refresh_run_info
        from db.read.engine import get_dashboard_read_session

        ensure_database_ready()
        with get_dashboard_read_session() as session:
            return load_latest_ai_refresh_run_info(session)
    except Exception:
        return None


def _cohort_preview_for_preset(preset: str):
    from db.bootstrap import ensure_database_ready
    from db.read.ai_refresh_cohort import preview_ai_refresh_cohort
    from db.read.engine import get_dashboard_read_session

    ensure_database_ready()
    with get_dashboard_read_session() as session:
        return preview_ai_refresh_cohort(session, preset)


def _format_ai_refresh_openai_request_estimate(estimated_batches: int) -> str:
    count = max(0, int(estimated_batches or 0))
    if count == 0:
        return "No requests expected"
    if count == 1:
        return "About 1 OpenAI request"
    return f"Approximately {count:,} OpenAI requests"


def _ai_refresh_preview_card_html(preview: object) -> str:
    cohort = int(getattr(preview, "cohort_size", 0) or 0)
    ready = int(getattr(preview, "eligible_with_description", 0) or 0)
    estimate = _format_ai_refresh_openai_request_estimate(
        int(getattr(preview, "estimated_batches", 0) or 0)
    )

    def _stat_row(label: str, value: str) -> str:
        return (
            '<div class="op-ai-refresh-preview-stat">'
            f'<span class="op-ai-refresh-preview-label">{html.escape(label)}</span>'
            f'<span class="op-ai-refresh-preview-value">{html.escape(value)}</span>'
            "</div>"
        )

    return (
        '<div class="op-ai-refresh-preview-card">'
        '<p class="op-ai-refresh-preview-title">Current AI Refresh Preview</p>'
        f"{_stat_row('Current Cohort', f'{cohort:,}')}"
        f"{_stat_row('Ready for AI Scoring', f'{ready:,}')}"
        f"{_stat_row('Estimated OpenAI Requests', estimate)}"
        "</div>"
    )


def _render_ai_refresh_preview_card(preview: object) -> None:
    st.markdown(_ai_refresh_preview_card_html(preview), unsafe_allow_html=True)


def _ai_refresh_log_path() -> Path:
    log_dir = _REPO_ROOT / "logs" / "scheduled"
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return log_dir / f"ai-refresh-{stamp}.log"


def _execute_ai_refresh_run(*, preset: str) -> tuple[bool, str]:
    from db.read.ai_refresh_cohort import AI_REFRESH_PRESETS

    script = _REPO_ROOT / "scripts" / "run_ai_refresh.py"
    if not script.is_file():
        return False, f"Script not found: {script}"
    preset_key = str(preset or "backlog").strip().lower()
    log_path = _ai_refresh_log_path()
    env = os.environ.copy()
    env["AI_REFRESH_LOG_FILE"] = str(log_path)
    try:
        subprocess.Popen(
            [_ai_refresh_python(), str(script), "--preset", preset_key],
            cwd=str(_REPO_ROOT),
            env=env,
            start_new_session=True,
        )
    except OSError as exc:
        return False, str(exc)
    label = AI_REFRESH_PRESETS.get(preset_key, preset_key)
    return True, f"Started {label} in background. Log: {log_path}"


def _open_ai_refresh_run_dialog(*, default_preset: str) -> None:
    from db.read.ai_refresh_cohort import AI_REFRESH_PRESET_BACKLOG, AI_REFRESH_PRESETS

    @st.dialog("Run Refresh AI Evaluations now?")
    def _dialog() -> None:
        st.markdown(
            "Re-scores existing jobs from SQLite descriptions using the current "
            "candidate profile. Uses the OpenAI API. Does not re-scrape or re-fetch descriptions."
        )
        preset = st.radio(
            "Preset",
            options=list(AI_REFRESH_PRESETS.keys()),
            format_func=lambda key: AI_REFRESH_PRESETS[key],
            index=0 if default_preset == AI_REFRESH_PRESET_BACKLOG else 1,
            key="op_ai_refresh_preset_dialog",
        )
        try:
            preview = _cohort_preview_for_preset(preset)
            _render_ai_refresh_preview_card(preview)
        except Exception as exc:
            st.warning(f"Could not load cohort preview: {exc}")

        cancel_col, confirm_col = st.columns(2)
        with cancel_col:
            if st.button("Cancel", key="dialog_cancel_ai_refresh", use_container_width=True):
                st.rerun()
        with confirm_col:
            if st.button(
                "Run now",
                key="dialog_confirm_ai_refresh",
                type="primary",
                use_container_width=True,
            ):
                ok, message = _execute_ai_refresh_run(preset=preset)
                if ok:
                    _mark_ai_refresh_polling_started()
                    st.success(message)
                else:
                    st.error(message)
                st.rerun()

    _dialog()


def _render_inline_ai_refresh_confirmation(*, default_preset: str) -> None:
    from db.read.ai_refresh_cohort import AI_REFRESH_PRESET_BACKLOG, AI_REFRESH_PRESETS

    if not st.session_state.get("op_run_confirm_ai_refresh"):
        return
    st.markdown(
        '<div class="op-run-confirm-panel">'
        '<p class="op-run-confirm-title">Run Refresh AI Evaluations now?</p>'
        '<p class="op-run-confirm-body">Uses OpenAI API; does not re-scrape or re-fetch descriptions.</p>'
        "</div>",
        unsafe_allow_html=True,
    )
    preset = st.radio(
        "Preset",
        options=list(AI_REFRESH_PRESETS.keys()),
        format_func=lambda key: AI_REFRESH_PRESETS[key],
        index=0 if default_preset == AI_REFRESH_PRESET_BACKLOG else 1,
        key="op_ai_refresh_preset_inline",
        horizontal=True,
    )
    try:
        preview = _cohort_preview_for_preset(preset)
        _render_ai_refresh_preview_card(preview)
    except Exception:
        pass
    cancel_col, confirm_col = st.columns(2)
    with cancel_col:
        if st.button("Cancel", key="inline_cancel_ai_refresh", use_container_width=True):
            st.session_state.pop("op_run_confirm_ai_refresh", None)
            st.rerun()
    with confirm_col:
        if st.button(
            "Run now",
            key="inline_confirm_ai_refresh",
            type="primary",
            use_container_width=True,
        ):
            st.session_state.pop("op_run_confirm_ai_refresh", None)
            ok, message = _execute_ai_refresh_run(preset=preset)
            if ok:
                _mark_ai_refresh_polling_started()
                st.success(message)
            else:
                st.error(message)
            st.rerun()


def _format_ai_refresh_last_run_summary(
    last_run: dict[str, object] | None,
    *,
    preset_labels: dict[str, str],
) -> list[tuple[str, str]]:
    """Build operator-facing label/value rows for the AI Refresh card."""
    if not last_run:
        return [("Last completed run", "No runs yet")]

    completed_at = last_run.get("completed_at")
    run_id = last_run.get("run_id")
    if completed_at is not None and str(completed_at).strip():
        last_completed = format_monitor_timestamp(completed_at)
    elif run_id is not None:
        last_completed = f"Run {int(run_id)}"
    else:
        last_completed = "No runs yet"

    preset_key = str(last_run.get("preset") or "").strip().lower()
    preset_label = preset_labels.get(preset_key, preset_key or "—")
    scored_count = int(last_run.get("scored_count") or 0)

    rows: list[tuple[str, str]] = [
        ("Last completed run", last_completed),
        ("Preset", preset_label),
        ("Jobs scored", str(scored_count)),
    ]
    persist_skipped = int(last_run.get("persist_skipped_count") or 0)
    batch_failures = int(last_run.get("batch_failures") or 0)
    if persist_skipped > 0:
        rows.append(("Persist skipped", str(persist_skipped)))
    if batch_failures > 0:
        rows.append(("Batch failures", str(batch_failures)))
    return rows


def _render_ai_refresh_card_body(
    *,
    writes_enabled: bool,
    write_help: str | None,
    running: bool,
) -> None:
    from db.read.ai_refresh_cohort import AI_REFRESH_PRESETS

    status_label, status_tone = _ai_refresh_status_badge(running)
    last_run = _load_ai_refresh_last_run()
    summary_rows = _format_ai_refresh_last_run_summary(last_run, preset_labels=AI_REFRESH_PRESETS)

    with st.container(border=True):
        st.markdown(
            '<div class="op-card-title">Refresh AI Evaluations</div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            _card_meta_row("Current status", _status_badge_html(status_label, status_tone)),
            unsafe_allow_html=True,
        )
        for label, value in summary_rows:
            st.markdown(
                _card_meta_row(label, html.escape(value)),
                unsafe_allow_html=True,
            )

        _, center_col, _ = st.columns([1, 1, 1])
        with center_col:
            run_disabled = (not writes_enabled) or running
            run_help = write_help
            if running and writes_enabled:
                run_help = "An AI refresh run is already in progress."
            if st.button(
                "Run now",
                key="op_run_ai_refresh",
                disabled=run_disabled,
                help=run_help,
                use_container_width=True,
            ):
                if _dialog_supported():
                    _open_ai_refresh_run_dialog(default_preset="backlog")
                else:
                    st.session_state["op_run_confirm_ai_refresh"] = True
                    st.rerun()

        _render_inline_ai_refresh_confirmation(default_preset="backlog")


@st.fragment(run_every=timedelta(seconds=2))
def _render_ai_refresh_card_live(
    *,
    writes_enabled: bool,
    write_help: str | None,
) -> None:
    running = _ai_refresh_is_running()
    was_polling = bool(st.session_state.get(_AI_REFRESH_POLLING_KEY))
    if was_polling and not running:
        st.session_state.pop(_AI_REFRESH_POLLING_KEY, None)
        st.rerun(scope="app")
    _render_ai_refresh_card_body(
        writes_enabled=writes_enabled,
        write_help=write_help,
        running=running,
    )


def _render_ai_refresh_card(*, writes_enabled: bool, write_help: str | None) -> None:
    running = _ai_refresh_is_running()
    polling = bool(st.session_state.get(_AI_REFRESH_POLLING_KEY))
    if running or polling:
        _render_ai_refresh_card_live(writes_enabled=writes_enabled, write_help=write_help)
        return
    _render_ai_refresh_card_body(
        writes_enabled=writes_enabled,
        write_help=write_help,
        running=False,
    )


def _render_scheduler_card(
    *,
    title: str,
    entry: dict[str, object] | None,
    scheduler_key: str,
    writes_enabled: bool,
    write_help: str | None,
    lifecycle_resume_gated: bool = False,
    lifecycle_gate_reason: str = "",
) -> None:
    scheduler_label, scheduler_tone = _scheduler_status_badge(
        entry if isinstance(entry, dict) else None
    )
    execution_label, execution_tone = _execution_status_badge(
        running=_scheduler_is_executing(scheduler_key)
    )
    next_run = "—"
    if isinstance(entry, dict):
        next_run = _format_next_scheduled_run(entry.get("next_run_estimate"))

    with st.container(border=True):
        st.markdown(f'<div class="op-card-title">{html.escape(title)}</div>', unsafe_allow_html=True)
        st.markdown(
            _card_meta_row("Scheduler status", _status_badge_html(scheduler_label, scheduler_tone)),
            unsafe_allow_html=True,
        )
        st.markdown(
            _card_meta_row("Current status", _status_badge_html(execution_label, execution_tone)),
            unsafe_allow_html=True,
        )
        st.markdown(
            _card_meta_row("Next scheduled run", html.escape(next_run)),
            unsafe_allow_html=True,
        )

        pause_col, resume_col, run_col = st.columns([1, 1, 0.82])

        with pause_col:
            if st.button(
                "Pause",
                key=f"op_pause_{scheduler_key}",
                disabled=not writes_enabled,
                help=write_help,
                use_container_width=True,
            ):
                _set_scheduler_paused(scheduler_key, True)
                st.success(f"{title} soft pause enabled.")
                st.rerun()

        with resume_col:
            resume_disabled = (lifecycle_resume_gated and scheduler_key == "lifecycle") or not writes_enabled
            if st.button(
                "Resume",
                key=f"op_resume_{scheduler_key}",
                disabled=resume_disabled,
                use_container_width=True,
            ):
                if scheduler_key == "lifecycle" and not lifecycle_resume_gated:
                    if _dialog_supported():
                        _open_lifecycle_resume_dialog()
                    else:
                        ok, message = _resume_lifecycle_scheduler()
                        if ok:
                            st.success(f"{title} re-enabled. {message}")
                        else:
                            st.error(message)
                        st.rerun()
                else:
                    _set_scheduler_paused(scheduler_key, False)
                    st.success(f"{title} soft pause cleared.")
                    st.rerun()

        with run_col:
            if st.button(
                "Run now",
                key=f"op_run_{scheduler_key}",
                disabled=not writes_enabled,
                help=write_help,
                use_container_width=True,
            ):
                _handle_run_now_click(
                    scheduler_key=scheduler_key,
                    title=title,
                )

        if lifecycle_resume_gated and scheduler_key == "lifecycle":
            _, hint_col, _ = st.columns([1, 1, 0.82])
            with hint_col:
                st.markdown(
                    '<div class="op-lock-hint-row">'
                    '<div class="op-lock-hint">'
                    '<span class="op-lock-icon" aria-hidden="true">🔒</span>'
                    f"<span>{html.escape(_lifecycle_resume_hint(lifecycle_gate_reason))}</span>"
                    "</div></div>",
                    unsafe_allow_html=True,
                )

        _render_inline_run_confirmation(
            scheduler_key=scheduler_key,
            title=title,
        )


def _render_operational_controls_cards(
    *,
    acquisition: object,
    lifecycle: object,
    acquisition_paused: bool,
    lifecycle_paused: bool,
    writes_enabled: bool,
    write_help: str | None,
    lifecycle_gated: bool,
    lifecycle_gate_reason: str,
) -> None:
    c1, c2 = st.columns(2)
    with c1:
        _render_scheduler_card(
            title="Acquisition",
            entry=acquisition if isinstance(acquisition, dict) else None,
            scheduler_key="acquisition",
            writes_enabled=writes_enabled,
            write_help=write_help,
        )
    with c2:
        _render_scheduler_card(
            title="Lifecycle Monitor",
            entry=lifecycle if isinstance(lifecycle, dict) else None,
            scheduler_key="lifecycle",
            writes_enabled=writes_enabled,
            write_help=write_help,
            lifecycle_resume_gated=lifecycle_gated,
            lifecycle_gate_reason=lifecycle_gate_reason,
        )

    refresh_col, _ = st.columns(2)
    with refresh_col:
        _render_ai_refresh_card(writes_enabled=writes_enabled, write_help=write_help)

    override_value = _operator_override_label(acquisition_paused, lifecycle_paused)
    override_tone = "yellow" if acquisition_paused or lifecycle_paused else "grey"
    st.markdown(
        '<div class="op-override-row">'
        '<span class="op-row-label">Paused by operator</span>'
        f"{_status_badge_html(override_value, override_tone)}"
        "</div>",
        unsafe_allow_html=True,
    )


@st.fragment(run_every=timedelta(seconds=30))
def _render_operational_controls_live(
    *,
    acquisition: object,
    lifecycle: object,
    acquisition_paused: bool,
    lifecycle_paused: bool,
    writes_enabled: bool,
    write_help: str | None,
    lifecycle_gated: bool,
    lifecycle_gate_reason: str,
) -> None:
    had_execution = bool(st.session_state.get(_OP_OPERATOR_HAD_EXECUTION_KEY))
    executing = _operator_execution_active()
    if had_execution and not executing:
        st.session_state.pop(_OP_OPERATOR_HAD_EXECUTION_KEY, None)
        st.rerun(scope="app")
    st.session_state[_OP_OPERATOR_HAD_EXECUTION_KEY] = executing
    _render_operational_controls_cards(
        acquisition=acquisition,
        lifecycle=lifecycle,
        acquisition_paused=acquisition_paused,
        lifecycle_paused=lifecycle_paused,
        writes_enabled=writes_enabled,
        write_help=write_help,
        lifecycle_gated=lifecycle_gated,
        lifecycle_gate_reason=lifecycle_gate_reason,
    )


def render_operational_controls_section() -> None:
    _inject_operator_controls_css()
    st.markdown("---")
    _render_operational_controls_heading(
        "Scheduler status and local operator actions for acquisition, lifecycle monitoring, and AI evaluation refresh.",
        "Resume lifecycle remains gated until Phase 6 sign-off.",
        "Pause, resume, and run-now actions require SQLite dashboard writes.",
    )
    st.markdown(
        '<div class="op-controls-cards-anchor" aria-hidden="true"></div>',
        unsafe_allow_html=True,
    )

    if platform.system().lower() != "darwin":
        st.warning(
            "Scheduler controls are intended for macOS launchd on the local operator machine."
        )

    status = _load_scheduler_status()
    schedulers = status.get("schedulers") if isinstance(status.get("schedulers"), dict) else {}
    acquisition = schedulers.get("acquisition") if isinstance(schedulers, dict) else {}
    lifecycle = schedulers.get("lifecycle") if isinstance(schedulers, dict) else {}
    pause_state = (
        status.get("operator_scheduler")
        if isinstance(status.get("operator_scheduler"), dict)
        else {}
    )

    acquisition_paused = bool(pause_state.get("acquisition_paused"))
    lifecycle_paused = bool(pause_state.get("lifecycle_paused"))

    writes_enabled = dashboard_write_enabled()
    write_help = (
        "Enable SQLite dashboard writes (SQLITE_DASHBOARD_WRITE=1)."
        if not writes_enabled
        else None
    )

    if not writes_enabled:
        st.markdown(
            '<p class="op-readonly-note">'
            "<strong>Operator controls are currently in View Only mode.</strong> "
            "Enable dashboard write access to pause, resume, or manually start schedulers."
            "</p>",
            unsafe_allow_html=True,
        )

    lifecycle_gated = bool(status.get("lifecycle_resume_gated"))
    signoff = status.get("ohm_signoff") if isinstance(status.get("ohm_signoff"), dict) else {}
    if lifecycle_gated:
        gate_reason = str(status.get("lifecycle_resume_gate_reason") or "").strip()
        if gate_reason:
            st.caption(gate_reason)
        if writes_enabled:
            ladder_done = bool(signoff.get("validation_ladder_passed"))
            s_col1, s_col2 = st.columns(2)
            with s_col1:
                if st.button("Record validation ladder passed", key="ohm_record_ladder"):
                    from agent.ohm_signoff import record_validation_ladder_passed

                    record_validation_ladder_passed()
                    st.success("Validation ladder marked passed.")
                    st.rerun()
            with s_col2:
                approve_disabled = not ladder_done
                if st.button(
                    "Approve lifecycle re-enable",
                    key="ohm_approve_resume",
                    disabled=approve_disabled,
                    help=(
                        "Complete and record the validation ladder first."
                        if approve_disabled
                        else "Record explicit operator approval for lifecycle re-enable."
                    ),
                ):
                    st.session_state["ohm_approve_dialog_open"] = True
            if st.session_state.get("ohm_approve_dialog_open"):
                _open_lifecycle_approve_dialog()

    card_kwargs = {
        "acquisition": acquisition,
        "lifecycle": lifecycle,
        "acquisition_paused": acquisition_paused,
        "lifecycle_paused": lifecycle_paused,
        "writes_enabled": writes_enabled,
        "write_help": write_help,
        "lifecycle_gated": lifecycle_gated,
        "lifecycle_gate_reason": str(status.get("lifecycle_resume_gate_reason") or ""),
    }
    if _operator_execution_poll_needed():
        _render_operational_controls_live(**card_kwargs)
    else:
        st.session_state.pop(_OP_OPERATOR_HAD_EXECUTION_KEY, None)
        _render_operational_controls_cards(**card_kwargs)
