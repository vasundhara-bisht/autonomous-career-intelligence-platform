"""Outreach Intelligence dashboard section (V1 / V1.1)."""

from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from date_display import (
    DASHBOARD_DATE_INPUT_HINT,
    dashboard_date_input_value,
    format_dashboard_date,
    parse_dashboard_date_input,
)
from db.services.outreach_write import insert_outreach_attempt, persist_outreach_table_edits
from outreach_ingest_guard import (
    SAVE_SUCCESS_MESSAGE,
    clear_duplicate_hiring_signal,
    consume_outreach_save_success,
    duplicate_hiring_signal_warning_lines,
    existing_outreach_record_snapshot,
    find_existing_outreach_by_hiring_signal_url,
    find_existing_outreach_by_opportunity_id,
    get_duplicate_hiring_signal,
    get_focus_outreach_record_id,
    clear_focus_outreach_record,
    request_outreach_save_success,
    should_fetch_hiring_signal_details,
    store_duplicate_hiring_signal,
)
from outreach_metrics import compute_outreach_metrics
from outreach_prefill import build_job_prefill_options, prefill_for_job_label
from outreach_signal_prefill import merge_outreach_form_defaults
from outreach_status import (
    HIRING_SIGNAL_FILTER_OPTIONS,
    HIRING_SIGNAL_LABEL_OPTIONS,
    HIRING_SIGNAL_NOT_SET,
    HIRING_SIGNAL_OPTIONS,
    OUTREACH_CHANNEL_OPTIONS,
    OUTREACH_STATUS_LABEL_OPTIONS,
    OUTREACH_STATUS_OPTIONS,
    hiring_signal_filter_label,
    hiring_signal_label,
    normalize_hiring_signal_type,
    normalize_outreach_channel,
    normalize_outreach_status,
    outreach_channel_label,
    outreach_status_label,
)
from ui_help import render_field_label_with_help, render_subheader_with_help

try:
    from agent.hiring_signal_extract import extract_hiring_signal_draft
    from agent.job_outreach_prefill import run_job_outreach_prefill
    from agent.outreach_message_generate import generate_outreach_message
    from agent.profile_loader import load_candidate_profile
    from db.engine import get_session as _get_db_session
    from db.read.job_outreach import load_job_outreach_context
    from outreach.linkedin_post_fetch import (
        LinkedInPostFetchError,
        fetch_hiring_signal_context,
    )
    from outreach.linkedin_post_url import LinkedInPostUrlError, validate_linkedin_post_url
except ImportError:  # pragma: no cover - dashboard path setup in tests
    extract_hiring_signal_draft = None  # type: ignore[assignment]
    run_job_outreach_prefill = None  # type: ignore[assignment]
    generate_outreach_message = None  # type: ignore[assignment]
    load_candidate_profile = None  # type: ignore[assignment]
    _get_db_session = None  # type: ignore[assignment]
    load_job_outreach_context = None  # type: ignore[assignment]
    fetch_hiring_signal_context = None  # type: ignore[assignment]
    validate_linkedin_post_url = None  # type: ignore[assignment]
    LinkedInPostFetchError = RuntimeError  # type: ignore[misc, assignment]
    LinkedInPostUrlError = ValueError  # type: ignore[misc, assignment]

_INGEST_DRAFT_KEY = "outreach_ingest_draft"
_FETCH_URL_INPUT_KEY = "outreach_fetch_url_input"
_FETCH_URL_STATE_KEY = "outreach_fetch_url"
_RESET_PENDING_KEY = "outreach_ingest_reset_pending"
_ADD_OUTREACH_EXPANDED_KEY = "outreach_add_expanded"
_RECOMMENDED_MESSAGE_KEY = "outreach_recommended_message_ai"
_PROFILE_SNAPSHOT_KEY = "outreach_candidate_profile_snapshot"
_OUTREACH_ADD_SAVE_KEY = "outreach_add_form_save"
_OUTREACH_ADD_CANCEL_KEY = "outreach_add_form_cancel"
_OUTREACH_ADD_REGEN_KEY = "outreach_add_form_regenerate"
_OUTREACH_TYPE_KEY = "outreach_type_selector"
_OUTREACH_TYPE_PREV_KEY = "outreach_type_selector_prev"
_JOB_SELECT_KEY = "outreach_job_select_v2"
_JOB_URL_STATE_KEY = "outreach_job_url_state"
_JOB_DESCRIPTION_SNAPSHOT_KEY = "outreach_job_description_snapshot"
_OUTREACH_TYPES = ("Hiring Signal Outreach", "Job Outreach")
_OUTREACH_ADD_FORM_BUTTON_CSS = """
<style>
/* ── Form field labels: consistent bold ────────────────────────────── */
div[data-testid="stForm"] label p {
    font-weight: 600 !important;
}

/* ── Outreach Message inline label (custom rendered in column) ──────── */
div[data-testid="stMarkdownContainer"] p.outreach-regen-label {
    font-size: 0.875rem !important;
    font-weight: 600 !important;
    margin: 0 0 0.25rem 0 !important;
    line-height: 1.6 !important;
    color: inherit !important;
}

/* ── Save Outreach button ───────────────────────────────────────────── */
.st-key-outreach_add_form_save button {
    background-color: #d8f3dc !important;
    color: #1b4332 !important;
    border: 1px solid #b7e4c7 !important;
}
.st-key-outreach_add_form_save button:hover:not(:disabled) {
    background-color: #c7ecd4 !important;
    border-color: #95d5b2 !important;
    color: #1b4332 !important;
}

/* ── Cancel button ──────────────────────────────────────────────────── */
.st-key-outreach_add_form_cancel button {
    background-color: #fde8e8 !important;
    color: #7f1d1d !important;
    border: 1px solid #f5c2c2 !important;
}
.st-key-outreach_add_form_cancel button:hover:not(:disabled) {
    background-color: #fbd5d5 !important;
    border-color: #f0abab !important;
    color: #7f1d1d !important;
}

/* ── Regenerate button: compact, light blue ─────────────────────────── */
.st-key-outreach_add_form_regenerate button {
    background-color: #dbeafe !important;
    color: #1e40af !important;
    border: 1px solid #93c5fd !important;
    font-size: 0.8rem !important;
    padding: 0.2rem 0.65rem !important;
    width: auto !important;
    min-width: unset !important;
}
.st-key-outreach_add_form_regenerate button:hover:not(:disabled) {
    background-color: #bfdbfe !important;
    border-color: #60a5fa !important;
    color: #1e3a8a !important;
}
</style>
"""
_FOLLOWUP_FILTERS = ("All", "Due today", "Overdue", "No follow-up set")
_SIGNAL_PLACEHOLDER = ""
_LINKED_JOB_COLUMN = "Linked Job"
_OUTREACH_STATUS_COLUMN = "Outreach Status"
_SIGNAL_TYPE_COLUMN = "Signal Type"
_EDITABLE_FIELD_COLUMNS = {
    "status": _OUTREACH_STATUS_COLUMN,
    "follow_up_date": "Follow-Up",
    "notes": "Hiring Signal Notes",
    "date_contacted": "Date Contacted",
    "hiring_signal_type": _SIGNAL_TYPE_COLUMN,
    "hiring_signal_url": "Hiring Signal URL",
}


def _truncate(text: str, limit: int = 48) -> str:
    text = str(text or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _linked_job_display(row: pd.Series) -> str:
    url = str(row.get("opportunity_url", "") or "").strip()
    if url:
        return _truncate(url)
    opp_id = str(row.get("opportunity_id", "") or "").strip()
    return _truncate(opp_id) if opp_id else ""


def _signal_table_display(stored_value: object, *, write_enabled: bool) -> str:
    normalized = normalize_hiring_signal_type(stored_value)
    if normalized:
        return hiring_signal_label(normalized)
    return "" if write_enabled else "Not set"


def _signal_bucket(value: object) -> str:
    normalized = normalize_hiring_signal_type(value)
    return normalized if normalized else HIRING_SIGNAL_NOT_SET


def filter_outreach_df(
    df: pd.DataFrame,
    *,
    selected_statuses: list[str],
    followup_filter: str,
    selected_signal_types: list[str],
    reference_date: date,
) -> pd.DataFrame:
    if df.empty:
        return df.copy()

    out = df.copy()
    if selected_statuses:
        normalized = out["status"].map(normalize_outreach_status)
        out = out[normalized.isin(selected_statuses)]

    if selected_signal_types:
        buckets = out["hiring_signal_type"].map(_signal_bucket)
        out = out[buckets.isin(selected_signal_types)]

    if followup_filter == "No follow-up set":
        out = out[out["follow_up_date"].fillna("").astype(str).str.strip() == ""]
    elif followup_filter in ("Due today", "Overdue"):
        ref = reference_date.isoformat()
        follow = out["follow_up_date"].fillna("").astype(str).str.strip()
        terminal = out["status"].map(normalize_outreach_status).isin(
            ("closed", "no_response")
        )
        has_follow = follow != ""
        if followup_filter == "Due today":
            out = out[has_follow & (follow == ref) & ~terminal]
        else:
            out = out[has_follow & (follow < ref) & ~terminal]

    return out.reset_index(drop=True)


def _persistable_outreach_dates(
    date_contacted: str, follow_up_date: str
) -> tuple[str, str | None]:
    contacted = parse_dashboard_date_input(date_contacted)
    if not contacted:
        raise ValueError(f"Date contacted must be {DASHBOARD_DATE_INPUT_HINT}")
    return contacted, parse_dashboard_date_input(follow_up_date)


def collect_outreach_table_edits(
    before_df: pd.DataFrame,
    after_df: pd.DataFrame,
) -> list[dict]:
    if before_df.empty or after_df.empty:
        return []

    edits: list[dict] = []
    for _, row in after_df.iterrows():
        row_id = row.get("id")
        if row_id is None or pd.isna(row_id):
            continue
        match = before_df[before_df["id"] == row_id]
        if match.empty:
            continue
        prev = match.iloc[0]
        payload: dict = {"id": int(row_id)}
        changed = False
        for field, column in _EDITABLE_FIELD_COLUMNS.items():
            new_val = str(row.get(column, "") or "").strip()
            old_val = str(prev.get(column, "") or "").strip()
            if field == "status":
                new_val = normalize_outreach_status(new_val)
                old_val = normalize_outreach_status(old_val)
            elif field == "hiring_signal_type":
                new_val = normalize_hiring_signal_type(new_val)
                old_val = normalize_hiring_signal_type(old_val)
                if not new_val:
                    continue
            elif field in ("date_contacted", "follow_up_date"):
                new_iso = parse_dashboard_date_input(new_val)
                old_iso = parse_dashboard_date_input(old_val)
                new_val = new_iso or new_val
                old_val = old_iso or old_val
            if new_val != old_val:
                payload[field] = new_val
                changed = True
        if changed:
            edits.append(payload)
    return edits


def _session_get(session_state: object, key: str, default: object = "") -> object:
    if isinstance(session_state, dict):
        return session_state.get(key, default)
    return getattr(session_state, key, default)


def _session_set(session_state: object, key: str, value: object) -> None:
    if isinstance(session_state, dict):
        session_state[key] = value
    else:
        setattr(session_state, key, value)


def _session_delete(session_state: object, key: str) -> None:
    if isinstance(session_state, dict):
        session_state.pop(key, None)
        return
    if hasattr(session_state, key):
        delattr(session_state, key)


def _clear_outreach_ingest_state(session_state: object) -> None:
    """Clear ingest draft and fetch URL state. Call only before widgets render."""
    _session_set(session_state, _INGEST_DRAFT_KEY, {})
    _session_set(session_state, _FETCH_URL_STATE_KEY, "")
    _session_delete(session_state, _FETCH_URL_INPUT_KEY)
    _session_delete(session_state, _RECOMMENDED_MESSAGE_KEY)
    _session_delete(session_state, _PROFILE_SNAPSHOT_KEY)
    _session_delete(session_state, _JOB_DESCRIPTION_SNAPSHOT_KEY)
    _session_delete(session_state, _JOB_URL_STATE_KEY)
    _session_delete(session_state, _JOB_SELECT_KEY)


def request_outreach_ingest_reset(session_state: object) -> None:
    """Schedule ingest reset for the next rerun, before widgets are created."""
    _session_set(session_state, _RESET_PENDING_KEY, True)


def apply_pending_outreach_ingest_reset(session_state: object) -> bool:
    """Apply a scheduled ingest reset at the start of a run. Returns True if cleared."""
    if not _session_get(session_state, _RESET_PENDING_KEY, False):
        return False
    _clear_outreach_ingest_state(session_state)
    _session_set(session_state, _RESET_PENDING_KEY, False)
    return True


def reset_outreach_ingest_state(session_state: object) -> None:
    """Backward-compatible alias for pre-widget clears in tests."""
    _clear_outreach_ingest_state(session_state)


def open_add_outreach_expander(session_state: object) -> None:
    _session_set(session_state, _ADD_OUTREACH_EXPANDED_KEY, True)


def close_add_outreach_expander(session_state: object) -> None:
    _session_set(session_state, _ADD_OUTREACH_EXPANDED_KEY, False)


def show_pending_outreach_save_toast(session_state: object) -> None:
    """Show a one-time toast after successful save (survives rerun, no banner)."""
    if consume_outreach_save_success(session_state):
        st.toast(SAVE_SUCCESS_MESSAGE, icon="✅")


def request_outreach_add_cancel(session_state: object) -> None:
    """Clear ingest workflow state and collapse Add Outreach."""
    request_outreach_ingest_reset(session_state)
    clear_duplicate_hiring_signal(session_state)
    clear_focus_outreach_record(session_state)
    close_add_outreach_expander(session_state)


def _run_hiring_signal_ingest(
    signal_url: str,
) -> tuple[dict[str, str], str | None, str | None]:
    if validate_linkedin_post_url is None or fetch_hiring_signal_context is None:
        return {}, "Hiring signal ingestion is unavailable in this environment.", None
    try:
        normalized_url = validate_linkedin_post_url(signal_url)
    except LinkedInPostUrlError as exc:
        return {}, str(exc), None

    try:
        context = fetch_hiring_signal_context(normalized_url)
    except LinkedInPostFetchError as exc:
        return {}, str(exc), None

    if extract_hiring_signal_draft is None:
        return {}, "Hiring signal ingestion is unavailable in this environment.", None

    draft, ai_ok = extract_hiring_signal_draft(context)
    message = None if ai_ok else "AI extraction partial — review all fields before saving."
    return draft.to_prefill_dict(), message, context.profile_warning


def _build_editor_df(df: pd.DataFrame, *, write_enabled: bool) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(
            columns=[
                "id",
                "#",
                "Person",
                "Designation",
                "Company",
                _SIGNAL_TYPE_COLUMN,
                _OUTREACH_STATUS_COLUMN,
                "Date Contacted",
                "Follow-Up",
                _LINKED_JOB_COLUMN,
                "Hiring Signal URL",
                "Hiring Signal Notes",
                "hiring_signal_type",
                "hiring_signal_url",
            ]
        )

    editor = df.copy()
    editor.insert(0, "#", range(1, len(editor) + 1))
    editor["hiring_signal_type"] = editor["hiring_signal_type"].map(
        normalize_hiring_signal_type
    )
    editor[_SIGNAL_TYPE_COLUMN] = editor["hiring_signal_type"].map(
        lambda value: _signal_table_display(value, write_enabled=write_enabled)
    )
    editor[_OUTREACH_STATUS_COLUMN] = editor["status"].map(outreach_status_label)
    editor["Person"] = editor["person_name"]
    editor["Designation"] = editor["designation"].fillna("").astype(str)
    editor["Company"] = editor["company"]
    editor["Date Contacted"] = editor["date_contacted"].map(format_dashboard_date)
    editor["Follow-Up"] = editor["follow_up_date"].map(format_dashboard_date)
    editor[_LINKED_JOB_COLUMN] = editor.apply(_linked_job_display, axis=1)
    editor["hiring_signal_url"] = editor["hiring_signal_url"].fillna("").astype(str)
    editor["Hiring Signal URL"] = editor["hiring_signal_url"]
    editor["Hiring Signal Notes"] = editor["notes"]
    return editor[
        [
            "id",
            "#",
            "Person",
            "Designation",
            "Company",
            _SIGNAL_TYPE_COLUMN,
            _OUTREACH_STATUS_COLUMN,
            "Date Contacted",
            "Follow-Up",
            _LINKED_JOB_COLUMN,
            "Hiring Signal URL",
            "Hiring Signal Notes",
            "hiring_signal_type",
            "hiring_signal_url",
        ]
    ]


def render_outreach_intelligence_section(
    *,
    outreach_df: pd.DataFrame,
    editor_df: pd.DataFrame,
    reference_date: date,
    write_enabled: bool,
) -> None:
    st.markdown("---")
    render_subheader_with_help(
        "Outreach Intelligence",
        "Track outreach conversations, referrals, and hiring leads.",
        "Not a CRM. Relationship stages live in Recruiter Relationship Management above.",
    )

    if not write_enabled:
        st.info(
            "Outreach logging requires SQLite dashboard writes "
            "(SQLITE_DASHBOARD_WRITE=1)."
        )

    show_pending_outreach_save_toast(st.session_state)

    metrics = compute_outreach_metrics(outreach_df, reference_date=reference_date)
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Total Outreach Records", metrics.total)
    k2.metric("Active Outreach", metrics.active)
    k3.metric("Follow-Ups Due Today", metrics.follow_ups_due_today)
    k4.metric("Overdue Follow-Ups", metrics.overdue_follow_ups)

    if "outreach_status_filter" not in st.session_state:
        st.session_state.outreach_status_filter = list(OUTREACH_STATUS_OPTIONS)
    if "outreach_followup_filter" not in st.session_state:
        st.session_state.outreach_followup_filter = "All"
    if "outreach_signal_filter" not in st.session_state:
        st.session_state.outreach_signal_filter = list(HIRING_SIGNAL_FILTER_OPTIONS)

    f1, f2, f3 = st.columns(3)
    with f1:
        st.session_state.outreach_status_filter = st.multiselect(
            _OUTREACH_STATUS_COLUMN,
            options=list(OUTREACH_STATUS_OPTIONS),
            default=st.session_state.outreach_status_filter,
            format_func=outreach_status_label,
        )
    with f2:
        st.session_state.outreach_followup_filter = st.selectbox(
            "Follow-up",
            options=list(_FOLLOWUP_FILTERS),
            index=list(_FOLLOWUP_FILTERS).index(
                st.session_state.outreach_followup_filter
            )
            if st.session_state.outreach_followup_filter in _FOLLOWUP_FILTERS
            else 0,
        )
    with f3:
        st.session_state.outreach_signal_filter = st.multiselect(
            "Hiring signal",
            options=list(HIRING_SIGNAL_FILTER_OPTIONS),
            default=st.session_state.outreach_signal_filter,
            format_func=hiring_signal_filter_label,
        )

    filtered_df = filter_outreach_df(
        outreach_df,
        selected_statuses=st.session_state.outreach_status_filter,
        followup_filter=st.session_state.outreach_followup_filter,
        selected_signal_types=st.session_state.outreach_signal_filter,
        reference_date=reference_date,
    )

    if _ADD_OUTREACH_EXPANDED_KEY not in st.session_state:
        st.session_state[_ADD_OUTREACH_EXPANDED_KEY] = False

    with st.expander(
        "Add Outreach",
        expanded=bool(st.session_state[_ADD_OUTREACH_EXPANDED_KEY]),
    ):
        apply_pending_outreach_ingest_reset(st.session_state)

        # ── Outreach type selector ──────────────────────────────────────────
        if _OUTREACH_TYPE_KEY not in st.session_state:
            st.session_state[_OUTREACH_TYPE_KEY] = _OUTREACH_TYPES[0]

        selected_outreach_type = st.radio(
            "Outreach Type",
            options=_OUTREACH_TYPES,
            horizontal=True,
            key=_OUTREACH_TYPE_KEY,
        )
        _is_job_outreach = selected_outreach_type == "Job Outreach"

        # Clear ingest state when operator switches outreach type.
        _prev_type = st.session_state.get(_OUTREACH_TYPE_PREV_KEY, selected_outreach_type)
        if _prev_type != selected_outreach_type:
            _clear_outreach_ingest_state(st.session_state)
            clear_duplicate_hiring_signal(st.session_state)
        st.session_state[_OUTREACH_TYPE_PREV_KEY] = selected_outreach_type

        if _INGEST_DRAFT_KEY not in st.session_state:
            st.session_state[_INGEST_DRAFT_KEY] = {}

        # ── PRE-FORM: Hiring Signal Outreach (frozen, unchanged) ───────────
        if not _is_job_outreach:
            job_options = build_job_prefill_options(editor_df)
            job_labels = [label for label, _ in job_options]
            selected_job = st.selectbox(
                "Link to job (optional)",
                options=job_labels,
                key="outreach_job_select",
            )
            job_prefill = prefill_for_job_label(editor_df, selected_job)

            if _FETCH_URL_INPUT_KEY not in st.session_state:
                st.session_state[_FETCH_URL_INPUT_KEY] = str(
                    st.session_state.get(_FETCH_URL_STATE_KEY, "") or ""
                )

            render_field_label_with_help(
                "Hiring Signal URL",
                "Fetch Details fills empty fields only.",
                "Existing values are preserved.",
                "Linked Job selection is never cleared.",
            )
            fetch_url = st.text_input(
                "Hiring Signal URL",
                key=_FETCH_URL_INPUT_KEY,
                label_visibility="collapsed",
                disabled=not write_enabled,
            )
            fetch_clicked = st.button(
                "Fetch Details",
                disabled=not write_enabled,
                key="outreach_fetch_linkedin",
            )
            if fetch_clicked:
                if should_fetch_hiring_signal_details(outreach_df, fetch_url):
                    clear_duplicate_hiring_signal(st.session_state)
                    with st.spinner("Fetching LinkedIn post and profile…"):
                        draft, ingest_message, profile_warning = _run_hiring_signal_ingest(
                            fetch_url
                        )
                    if ingest_message and not draft:
                        st.error(ingest_message)
                    elif draft:
                        try:
                            candidate_profile = load_candidate_profile() if load_candidate_profile else ""
                        except Exception:
                            candidate_profile = ""
                        st.session_state[_PROFILE_SNAPSHOT_KEY] = candidate_profile

                        if generate_outreach_message:
                            rec_msg, msg_ok = generate_outreach_message(
                                person_name=draft.get("person_name", ""),
                                designation=draft.get("designation", ""),
                                company=draft.get("company", ""),
                                notes=draft.get("notes", ""),
                                hiring_signal_type=draft.get("hiring_signal_type", ""),
                                candidate_profile=candidate_profile,
                            )
                            if rec_msg:
                                draft = dict(draft)
                                draft["outreach_message"] = rec_msg
                                st.session_state[_RECOMMENDED_MESSAGE_KEY] = rec_msg
                            elif not msg_ok:
                                st.warning("Message generation unavailable — fill manually.")

                        st.session_state[_INGEST_DRAFT_KEY] = draft
                        st.session_state[_FETCH_URL_STATE_KEY] = fetch_url
                        open_add_outreach_expander(st.session_state)
                        if profile_warning:
                            st.warning(profile_warning)
                        if ingest_message:
                            st.warning(ingest_message)
                        st.toast("Draft prefilled — review before saving", icon="✅")
                        st.rerun()
                    else:
                        st.error("Could not build outreach draft from LinkedIn post.")
                else:
                    existing_record = find_existing_outreach_by_hiring_signal_url(
                        outreach_df,
                        fetch_url,
                    )
                    if existing_record:
                        store_duplicate_hiring_signal(st.session_state, existing_record)
                        open_add_outreach_expander(st.session_state)

            duplicate_record = get_duplicate_hiring_signal(st.session_state)
            if duplicate_record:
                warning_lines = duplicate_hiring_signal_warning_lines(duplicate_record)
                st.warning(warning_lines[0])
                for line in warning_lines[1:]:
                    st.markdown(line)

        # ── PRE-FORM: Job Outreach (new) ────────────────────────────────────
        else:
            job_options = build_job_prefill_options(editor_df)
            job_labels = [label for label, _ in job_options]
            selected_job_label = st.selectbox(
                "Job :red[*]",
                options=job_labels,
                key=_JOB_SELECT_KEY,
                format_func=lambda x: "Select a job…" if x == "None" else x,
            )

            stored_job_url = str(st.session_state.get(_JOB_URL_STATE_KEY, "") or "")
            if stored_job_url:
                st.text_input(
                    "Job URL",
                    value=stored_job_url,
                    disabled=True,
                )

            job_fetch_clicked = st.button(
                "Fetch Details",
                disabled=not write_enabled,
                key="outreach_fetch_job",
            )
            if job_fetch_clicked:
                _job_prefill_ctx = prefill_for_job_label(editor_df, selected_job_label)
                _job_key_v2 = _job_prefill_ctx.get("opportunity_id", "")
                if not _job_key_v2 or selected_job_label == "None":
                    st.error("Please select a job before fetching details.")
                else:
                    existing_job_outreach = find_existing_outreach_by_opportunity_id(
                        outreach_df, _job_key_v2
                    )
                    if existing_job_outreach:
                        store_duplicate_hiring_signal(st.session_state, existing_job_outreach)
                        open_add_outreach_expander(st.session_state)
                    else:
                        try:
                            candidate_profile = load_candidate_profile() if load_candidate_profile else ""
                        except Exception:
                            candidate_profile = ""
                        st.session_state[_PROFILE_SNAPSHOT_KEY] = candidate_profile

                        if load_job_outreach_context is not None and _get_db_session is not None:
                            try:
                                _jctx_session = _get_db_session()
                                try:
                                    _jctx = load_job_outreach_context(
                                        _jctx_session, _job_key_v2
                                    )
                                finally:
                                    _jctx_session.close()
                                st.session_state[_JOB_DESCRIPTION_SNAPSHOT_KEY] = (
                                    _jctx.description if _jctx else ""
                                )
                            except Exception:
                                st.session_state[_JOB_DESCRIPTION_SNAPSHOT_KEY] = ""

                        if run_job_outreach_prefill is not None:
                            with st.spinner("Loading job details…"):
                                _jo_draft, _jo_warning = run_job_outreach_prefill(
                                    _job_key_v2, candidate_profile
                                )
                            if not _jo_draft:
                                st.error(_jo_warning or "Could not load job details.")
                            else:
                                if _jo_warning:
                                    st.warning(_jo_warning)
                                st.session_state[_INGEST_DRAFT_KEY] = _jo_draft
                                if _jo_draft.get("outreach_message"):
                                    st.session_state[_RECOMMENDED_MESSAGE_KEY] = _jo_draft[
                                        "outreach_message"
                                    ]
                                st.session_state[_JOB_URL_STATE_KEY] = _jo_draft.get(
                                    "opportunity_url", ""
                                )
                                open_add_outreach_expander(st.session_state)
                                st.toast("Job details loaded — review before saving", icon="✅")
                                st.rerun()
                        else:
                            st.error("Job Outreach enrichment is unavailable in this environment.")

            duplicate_record = get_duplicate_hiring_signal(st.session_state)
            if duplicate_record:
                warning_lines = duplicate_hiring_signal_warning_lines(duplicate_record)
                st.warning(f"An outreach record already exists for this job.  {warning_lines[0]}")
                for line in warning_lines[1:]:
                    st.markdown(line)

            job_prefill = {}

        # ── Shared form defaults ────────────────────────────────────────────
        form_defaults = merge_outreach_form_defaults(
            job_prefill=job_prefill,
            ingest_draft=st.session_state.get(_INGEST_DRAFT_KEY, {}),
        )
        default_channel = normalize_outreach_channel(
            form_defaults.get("outreach_channel", "linkedin")
        )
        channel_index = (
            OUTREACH_CHANNEL_OPTIONS.index(default_channel)
            if default_channel in OUTREACH_CHANNEL_OPTIONS
            else 0
        )
        default_signal = normalize_hiring_signal_type(
            form_defaults.get("hiring_signal_type", "")
        )
        hiring_signal_options = [_SIGNAL_PLACEHOLDER, *HIRING_SIGNAL_OPTIONS]
        signal_index = (
            hiring_signal_options.index(default_signal)
            if default_signal in HIRING_SIGNAL_OPTIONS
            else 0
        )

        _show_regen_button = bool(
            st.session_state.get(_INGEST_DRAFT_KEY) and generate_outreach_message
        )

        # ── Shared form ────────────────────────────────────────────────────
        with st.form("outreach_add_form", clear_on_submit=True):
            person_name = st.text_input(
                "Person name :red[*]",
                value=form_defaults.get("person_name", ""),
            )
            company = st.text_input(
                "Company :red[*]",
                value=form_defaults.get("company", ""),
            )
            designation = st.text_input(
                "Designation",
                value=form_defaults.get("designation", ""),
            )
            linkedin_url = st.text_input(
                "LinkedIn Profile URL",
                value=form_defaults.get("linkedin_url", ""),
            )
            outreach_channel = st.selectbox(
                "Channel :red[*]",
                options=OUTREACH_CHANNEL_OPTIONS,
                index=channel_index,
                format_func=outreach_channel_label,
            )
            if not _is_job_outreach:
                hiring_signal_type = st.selectbox(
                    "Hiring signal type :red[*]",
                    options=hiring_signal_options,
                    index=signal_index,
                    format_func=lambda value: (
                        "Select hiring signal…"
                        if not value
                        else hiring_signal_label(value)
                    ),
                )
                hiring_signal_url = st.text_input(
                    "Hiring Signal URL (optional)",
                    value=form_defaults.get("hiring_signal_url", ""),
                )
            else:
                hiring_signal_type = "job_listing"
                hiring_signal_url = ""

            if _show_regen_button:
                _msg_label_col, _regen_col = st.columns([6, 2])
                with _msg_label_col:
                    st.markdown(
                        '<p class="outreach-regen-label">Outreach Message (Recommended)</p>',
                        unsafe_allow_html=True,
                    )
                with _regen_col:
                    regenerated = st.form_submit_button(
                        "Regenerate",
                        key=_OUTREACH_ADD_REGEN_KEY,
                        use_container_width=False,
                    )
            else:
                regenerated = False
            outreach_message = st.text_area(
                "Outreach Message (Recommended)",
                value=form_defaults.get("outreach_message", ""),
                height=180,
                label_visibility="collapsed" if _show_regen_button else "visible",
            )
            date_contacted = st.text_input(
                f"Date contacted ({DASHBOARD_DATE_INPUT_HINT}) :red[*]",
                value=dashboard_date_input_value(reference_date),
            )
            follow_up_date = st.text_input(
                f"Follow-up date ({DASHBOARD_DATE_INPUT_HINT})", value=""
            )
            status = st.selectbox(
                "Outreach status :red[*]",
                options=OUTREACH_STATUS_OPTIONS,
                index=OUTREACH_STATUS_OPTIONS.index("planned"),
                format_func=outreach_status_label,
            )
            if not _is_job_outreach:
                notes = st.text_area(
                    "Hiring Signal Notes",
                    value=form_defaults.get("notes", ""),
                    height=120,
                )
            else:
                notes = st.text_area(
                    "Notes (optional)",
                    value="",
                    height=120,
                )
            st.markdown(_OUTREACH_ADD_FORM_BUTTON_CSS, unsafe_allow_html=True)
            action_col, _ = st.columns([2.8, 7.2], gap="small")
            with action_col:
                save_col, cancel_col = st.columns(2, gap="small")
                with save_col:
                    submitted = st.form_submit_button(
                        "Save outreach",
                        disabled=not write_enabled,
                        key=_OUTREACH_ADD_SAVE_KEY,
                        use_container_width=True,
                    )
                with cancel_col:
                    cancelled = st.form_submit_button(
                        "Cancel",
                        key=_OUTREACH_ADD_CANCEL_KEY,
                        use_container_width=True,
                    )

        if regenerated:
            _regen_draft = dict(st.session_state.get(_INGEST_DRAFT_KEY) or {})
            if _regen_draft and generate_outreach_message:
                _regen_profile = str(
                    st.session_state.get(_PROFILE_SNAPSHOT_KEY) or ""
                )
                _regen_prev = str(
                    st.session_state.get(_RECOMMENDED_MESSAGE_KEY) or ""
                )
                _is_job_regen = _regen_draft.get("outreach_type") == "job_outreach"
                _regen_notes = (
                    str(st.session_state.get(_JOB_DESCRIPTION_SNAPSHOT_KEY) or "")
                    if _is_job_regen
                    else _regen_draft.get("notes", "")
                )
                _regen_msg, _ = generate_outreach_message(
                    person_name=_regen_draft.get("person_name", ""),
                    designation=_regen_draft.get("designation", ""),
                    company=_regen_draft.get("company", ""),
                    notes=_regen_notes,
                    hiring_signal_type=_regen_draft.get("hiring_signal_type", ""),
                    candidate_profile=_regen_profile,
                    previous_message=_regen_prev,
                )
                if _regen_msg:
                    _regen_draft["outreach_message"] = _regen_msg
                    st.session_state[_INGEST_DRAFT_KEY] = _regen_draft
                    st.session_state[_RECOMMENDED_MESSAGE_KEY] = _regen_msg
            st.rerun()

        if cancelled:
            request_outreach_add_cancel(st.session_state)
            st.rerun()

        if submitted:
            normalized_signal = normalize_hiring_signal_type(hiring_signal_type)
            if not normalized_signal:
                st.error("Hiring signal type is required.")
            elif not _is_job_outreach:
                # ── Hiring Signal save (frozen, unchanged) ──────────────────
                duplicate_on_save = (
                    find_existing_outreach_by_hiring_signal_url(
                        outreach_df,
                        hiring_signal_url,
                    )
                    if str(hiring_signal_url or "").strip()
                    else None
                )
                if duplicate_on_save:
                    store_duplicate_hiring_signal(st.session_state, duplicate_on_save)
                    open_add_outreach_expander(st.session_state)
                    st.error(
                        "This hiring signal already exists. "
                        "Open the existing record instead."
                    )
                else:
                    try:
                        contacted_iso, follow_iso = _persistable_outreach_dates(
                            date_contacted, follow_up_date
                        )
                    except ValueError as exc:
                        st.error(str(exc))
                    else:
                        payload = {
                            "person_name": person_name,
                            "company": company,
                            "designation": designation,
                            "linkedin_url": linkedin_url,
                            "outreach_channel": normalize_outreach_channel(outreach_channel),
                            "hiring_signal_type": normalized_signal,
                            "hiring_signal_url": hiring_signal_url,
                            "outreach_message": outreach_message,
                            "ai_recommended_message": str(
                                st.session_state.get(_RECOMMENDED_MESSAGE_KEY) or ""
                            ),
                            "date_contacted": contacted_iso,
                            "follow_up_date": follow_iso or "",
                            "status": normalize_outreach_status(status),
                            "notes": notes,
                            "opportunity_id": job_prefill.get("opportunity_id", ""),
                            "opportunity_url": job_prefill.get("opportunity_url", ""),
                        }
                        try:
                            row_id = insert_outreach_attempt(payload)
                        except ValueError as exc:
                            st.error(str(exc))
                        else:
                            if row_id:
                                request_outreach_save_success(st.session_state)
                                request_outreach_ingest_reset(st.session_state)
                                open_add_outreach_expander(st.session_state)
                                st.rerun()
                            else:
                                st.error("Could not save outreach (writes disabled).")
            else:
                # ── Job Outreach save ───────────────────────────────────────
                _jo_ingest = dict(st.session_state.get(_INGEST_DRAFT_KEY) or {})
                try:
                    contacted_iso, follow_iso = _persistable_outreach_dates(
                        date_contacted, follow_up_date
                    )
                except ValueError as exc:
                    st.error(str(exc))
                else:
                    payload = {
                        "person_name": person_name,
                        "company": company,
                        "designation": designation,
                        "linkedin_url": linkedin_url,
                        "outreach_channel": normalize_outreach_channel(outreach_channel),
                        "hiring_signal_type": "job_listing",
                        "hiring_signal_url": "",
                        "outreach_type": "job_outreach",
                        "outreach_message": outreach_message,
                        "ai_recommended_message": str(
                            st.session_state.get(_RECOMMENDED_MESSAGE_KEY) or ""
                        ),
                        "date_contacted": contacted_iso,
                        "follow_up_date": follow_iso or "",
                        "status": normalize_outreach_status(status),
                        "notes": notes,
                        "opportunity_id": _jo_ingest.get("opportunity_id", ""),
                        "opportunity_url": _jo_ingest.get("opportunity_url", ""),
                    }
                    try:
                        row_id = insert_outreach_attempt(payload)
                    except ValueError as exc:
                        st.error(str(exc))
                    else:
                        if row_id:
                            request_outreach_save_success(st.session_state)
                            request_outreach_ingest_reset(st.session_state)
                            open_add_outreach_expander(st.session_state)
                            st.rerun()
                        else:
                            st.error("Could not save outreach (writes disabled).")

    focus_record_id = get_focus_outreach_record_id(st.session_state)
    if focus_record_id is not None and not outreach_df.empty:
        focused = outreach_df[outreach_df["id"] == focus_record_id]
        if not focused.empty:
            snapshot = existing_outreach_record_snapshot(focused.iloc[0].to_dict())
            st.info(
                "Existing record: "
                f"{snapshot['person_name']} · {snapshot['company']} · "
                f"{snapshot['status_label']} · Created {snapshot['created_at']}"
            )

    table_df = _build_editor_df(filtered_df, write_enabled=write_enabled)
    if table_df.empty:
        st.caption("No outreach records match the current filters.")
        return

    editor_df = table_df.drop(columns=["hiring_signal_type", "hiring_signal_url"])
    signal_column: st.column_config.ColumnConfig = (
        st.column_config.SelectboxColumn(
            _SIGNAL_TYPE_COLUMN,
            options=HIRING_SIGNAL_LABEL_OPTIONS,
            width="medium",
            disabled=not write_enabled,
        )
        if write_enabled
        else st.column_config.TextColumn(_SIGNAL_TYPE_COLUMN, disabled=True)
    )
    status_column: st.column_config.ColumnConfig = (
        st.column_config.SelectboxColumn(
            _OUTREACH_STATUS_COLUMN,
            options=OUTREACH_STATUS_LABEL_OPTIONS,
            width="medium",
            disabled=not write_enabled,
        )
        if write_enabled
        else st.column_config.TextColumn(_OUTREACH_STATUS_COLUMN, disabled=True)
    )
    edited_df = st.data_editor(
        editor_df,
        key="outreach_table_editor",
        num_rows="fixed",
        width="stretch",
        hide_index=True,
        column_order=[
            "#",
            "Person",
            "Designation",
            "Company",
            _SIGNAL_TYPE_COLUMN,
            _OUTREACH_STATUS_COLUMN,
            "Date Contacted",
            "Follow-Up",
            _LINKED_JOB_COLUMN,
            "Hiring Signal URL",
            "Hiring Signal Notes",
        ],
        column_config={
            "id": None,
            "#": st.column_config.NumberColumn("#", width="small", disabled=True),
            "Person": st.column_config.TextColumn("Person", disabled=True),
            "Designation": st.column_config.TextColumn("Designation", disabled=True),
            "Company": st.column_config.TextColumn("Company", disabled=True),
            _SIGNAL_TYPE_COLUMN: signal_column,
            _OUTREACH_STATUS_COLUMN: status_column,
            "Date Contacted": st.column_config.TextColumn(
                "Date Contacted",
                disabled=not write_enabled,
            ),
            "Follow-Up": st.column_config.TextColumn(
                "Follow-Up",
                disabled=not write_enabled,
            ),
            _LINKED_JOB_COLUMN: st.column_config.TextColumn(
                _LINKED_JOB_COLUMN,
                disabled=True,
            ),
            "Hiring Signal URL": st.column_config.TextColumn(
                "Hiring Signal URL",
                width="medium",
                disabled=not write_enabled,
            ),
            "Hiring Signal Notes": st.column_config.TextColumn(
                "Hiring Signal Notes",
                width="large",
                disabled=not write_enabled,
            ),
        },
    )

    if write_enabled:
        before_editor = table_df.drop(columns=["hiring_signal_type", "hiring_signal_url"])
        edits = collect_outreach_table_edits(before_editor, edited_df)
        if edits:
            count = persist_outreach_table_edits(edits)
            if count:
                st.toast("Outreach updates saved", icon="✅")
                st.rerun()
