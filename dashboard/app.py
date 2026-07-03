import streamlit as st
import pandas as pd
import altair as alt
from datetime import date, datetime, timedelta

import paths
from agent.pipeline_stages import USER_MANAGED_PIPELINE_STAGES
from db.read.engine import dashboard_read_enabled, dashboard_write_enabled
from db.services.dashboard_write import (
    persist_dashboard_crm_edits,
    persist_dashboard_job_edits,
)
from data_flow import (
    SidebarFilterState,
    apply_discovery_score_filter,
    apply_sidebar_filters,
    build_dashboard_df,
    is_user_managed_stage,
    sort_for_table,
)
from date_display import format_dashboard_date
from funnel import compute_progression_funnel_counts
from funnel_workflow import (
    JOB_SEARCH_PROGRESSION_TITLE,
    render_job_search_progression_workflow,
)
from recruiter_funnel import compute_recruiter_progression_counts
from recruiter_stages import CRM_STATUS_OPTIONS
from recruiter_workflow import (
    RECRUITER_RELATIONSHIP_PROGRESSION_TITLE,
    render_recruiter_relationship_progression_workflow,
)
from recommended_actions_ui import render_recommended_actions_section
from outreach_ui import render_outreach_intelligence_section
from acquisition_ui import render_acquisition_health_section
from ai_refresh_ui import render_ai_refresh_health_section
from monitor_ui import render_operational_monitor_health_section
from operator_controls_ui import render_operational_controls_section
from source_display import source_display_name
from ui_help import inject_dashboard_help_css, render_refresh_labels_row, render_section_heading, render_subheader_with_help, render_subsection_heading
from loaders import (
    get_loader_diagnostics,
    load_dashboard_historical_df,
    load_dashboard_jobs_df,
    load_outreach_df,
    load_recruiter_crm_df,
    reset_loader_diagnostics,
)
from listing_visibility import (
    apply_listing_visibility,
    format_age_chip,
    format_listing_badge_row,
)
from job_editor import job_editor_return_differs_input
from job_listings_editor import (
    CLOSED_LISTING_READONLY_HELP,
    CLOSED_LISTINGS_SECTION_TITLE,
    closed_listings_readonly_column_config,
    filter_persisted_job_states,
    partition_editor_df_by_listing,
    style_closed_listings_display_df,
)

paths.migrate_legacy_root_runtime_files()

PRODUCT_TITLE = "Autonomous Career Intelligence Platform"

PIPELINE_STAGES = [
    "New",
    "Saved",
    "Applied",
    "HR Screen",
    "Interview",
    "Final Round",
    "Offer",
    "Rejected",
    "Ghosted",
]

DATE_RANGE_PRESETS = ("All time", "Last 7 days", "Last 30 days", "Custom")


# Re-export for tests and backward compatibility.
_is_user_managed_stage = is_user_managed_stage
_apply_listing_visibility = apply_listing_visibility
_apply_discovery_score_filter = apply_discovery_score_filter


def _ensure_merge_key_columns(df: pd.DataFrame) -> pd.DataFrame:
    """V2-first merge key; legacy JOB_KEY fallback (matches pipeline identity model)."""
    out = df.copy()
    if "JOB_KEY" not in out.columns:
        out["JOB_KEY"] = ""
    if "JOB_KEY_V2" not in out.columns:
        out["JOB_KEY_V2"] = ""
    leg = out["JOB_KEY"].fillna("").astype(str).str.strip()
    v2 = out["JOB_KEY_V2"].fillna("").astype(str).str.strip()
    out["__merge_key"] = v2.where(v2 != "", leg)
    return out


def _normalize_historical_state(df: pd.DataFrame) -> pd.DataFrame:
    """Pipeline and legacy boolean normalization for historical_state_df."""
    out = df.copy()

    for col in ("applied", "rejected", "interview", "offer"):
        if col in out.columns:
            out[col] = (
                out[col]
                .astype(str)
                .str.lower()
                .map({"true": True, "false": False})
                .fillna(False)
            )

    if "notes" in out.columns:
        out["notes"] = out["notes"].fillna("").astype(str)
    else:
        out["notes"] = ""

    if "pipeline_stage" not in out.columns:
        out["pipeline_stage"] = "New"
    out["pipeline_stage"] = (
        out["pipeline_stage"].fillna("New").astype(str).str.strip()
    )

    out["applied"] = out["pipeline_stage"].isin(
        ["Applied", "HR Screen", "Interview", "Final Round", "Offer"]
    )
    out["interview"] = out["pipeline_stage"].isin(
        ["Interview", "Final Round", "Offer"]
    )
    out["offer"] = out["pipeline_stage"] == "Offer"
    out["rejected"] = out["pipeline_stage"] == "Rejected"

    return out


def score_badge(score, ai_status):
    status = str(ai_status or "").strip().lower()
    if status == "not_required":
        return "Not Required"
    if status == "skipped_by_cap":
        return "Skipped (cap)"
    if status != "scored":
        return "Pending AI"
    if score >= 9:
        return f"🟢 {score}"
    if score >= 7:
        return f"🟡 {score}"
    return f"🔴 {score}"


def _path_mtime(path) -> float:
    return path.stat().st_mtime if path.is_file() else 0.0


def _format_refresh_label(ts: pd.Timestamp) -> str:
    return ts.strftime("%d %b %Y · %I:%M %p")


def _acquisition_completed_at_to_local(ts: pd.Timestamp) -> pd.Timestamp:
    """Acquisition DB timestamps are UTC-naive; convert to local time for display."""
    if ts.tzinfo is None:
        utc_ts = ts.tz_localize("UTC")
    else:
        utc_ts = ts.tz_convert("UTC")
    local_ts = utc_ts.tz_convert(datetime.now().astimezone().tzinfo)
    return local_ts.tz_localize(None)


@st.cache_data
def load_last_data_refresh_label(
    use_sqlite: bool, db_mtime: float, jobs_csv_mtime: float
) -> str:
    """
    Last successful acquisition refresh (not Streamlit render time).

    Primary: completed_at from latest_acquisition_run_view (dual-write at end of
    main.py). Fallback: jobs.csv mtime (DB export artifact after acquisition).
    """
    if use_sqlite:
        try:
            from db.bootstrap import ensure_database_ready
            from db.read.engine import get_dashboard_read_session
            from db.read.export_cohort import load_latest_run_info

            ensure_database_ready()
            with get_dashboard_read_session() as session:
                run_info = load_latest_run_info(session)
            if run_info and run_info.get("completed_at"):
                ts = pd.to_datetime(run_info["completed_at"], errors="coerce")
                if pd.notna(ts):
                    return _format_refresh_label(_acquisition_completed_at_to_local(ts))
        except Exception:
            pass

    jobs_path = paths.jobs_csv()
    if jobs_path.is_file():
        return _format_refresh_label(
            pd.Timestamp.fromtimestamp(jobs_path.stat().st_mtime)
        )
    return "Unknown"


@st.cache_data
def load_last_monitoring_refresh_label(use_sqlite: bool, db_mtime: float) -> str:
    """Last successful lifecycle monitor refresh (independent of listing UI flag)."""
    if not use_sqlite:
        return "Unknown"
    try:
        from db.bootstrap import ensure_database_ready
        from db.read.engine import get_dashboard_read_session
        from db.read.monitor_runs import load_latest_productive_monitor_run_info

        ensure_database_ready()
        with get_dashboard_read_session() as session:
            run_info = load_latest_productive_monitor_run_info(session)
        if run_info and run_info.get("completed_at"):
            ts = pd.to_datetime(run_info["completed_at"], errors="coerce")
            if pd.notna(ts):
                return _format_refresh_label(_acquisition_completed_at_to_local(ts))
    except Exception:
        pass
    return "Unknown"


def _format_posted_for_display(value: object) -> str:
    return format_dashboard_date(value)


def _build_editor_df(
    filtered_df: pd.DataFrame, historical_state_df: pd.DataFrame
) -> pd.DataFrame:
    display_df = filtered_df.copy()
    display_df["JOB_KEY"] = display_df["JOB_KEY"].astype(str).str.strip()
    display_df.reset_index(drop=True, inplace=True)

    display_df = display_df.drop(
        columns=[
            "applied",
            "rejected",
            "interview",
            "offer",
            "response_status",
        ],
        errors="ignore",
    )

    _hist_cols = [
        "applied",
        "rejected",
        "interview",
        "offer",
        "pipeline_stage",
        "notes",
    ]

    display_df = _ensure_merge_key_columns(display_df)
    _hist_merge = _ensure_merge_key_columns(historical_state_df)
    display_df = display_df.drop(
        columns=[c for c in _hist_cols if c in display_df.columns],
        errors="ignore",
    )
    display_df = display_df.merge(
        _hist_merge[
            [c for c in _hist_cols if c in _hist_merge.columns] + ["__merge_key"]
        ],
        on="__merge_key",
        how="left",
    )
    display_df = display_df.drop(columns=["__merge_key"], errors="ignore")

    state_defaults = {
        "applied": False,
        "rejected": False,
        "interview": False,
        "offer": False,
        "pipeline_stage": "New",
        "notes": "",
    }
    for col, default_value in state_defaults.items():
        if col not in display_df.columns:
            display_df[col] = default_value
        display_df[col] = display_df[col].fillna(default_value)

    for col in ("applied", "rejected", "interview", "offer"):
        display_df[col] = display_df[col].astype(bool)

    display_df = display_df.loc[:, ~display_df.columns.duplicated()]

    editor_df = display_df.copy()
    editor_df["source_key"] = editor_df["source"].fillna("").astype(str).str.strip()
    editor_df["ai_score_display"] = editor_df.apply(
        lambda row: score_badge(row["score"], row.get("ai_status")),
        axis=1,
    )
    editor_df["reason"] = editor_df["reason"].astype(str).str.slice(0, 120)
    if "posted_at_date" in editor_df.columns:
        editor_df["Posted"] = editor_df["posted_at_date"].map(_format_posted_for_display)
    else:
        editor_df["Posted"] = ""
    editor_df["Listing"] = display_df.apply(format_listing_badge_row, axis=1)
    if "listing_status" in display_df.columns:
        editor_df["listing_status"] = display_df["listing_status"]
    if "age_bucket" in display_df.columns:
        editor_df["Age"] = display_df["age_bucket"].map(format_age_chip)
    else:
        editor_df["Age"] = ""
    editor_df = editor_df.rename(
        columns={
            "title": "Title",
            "company": "Company",
            "location": "Location",
            "hiring_manager": "Hiring Manager",
            "ai_score_display": "AI Score",
            "reason": "Reason",
            "link": "Link",
            "pipeline_stage": "Status",
            "notes": "Notes",
        }
    )
    editor_df["Source"] = editor_df["source_key"].map(source_display_name)
    editor_df.insert(0, "#", range(1, len(editor_df) + 1))

    _editor_cols = [
        "#",
        "JOB_KEY",
        "Title",
        "Company",
        "Location",
        "Posted",
        "Hiring Manager",
        "AI Score",
        "Reason",
        "source_key",
        "Source",
        "Link",
        "Status",
        "Notes",
    ]
    if "JOB_KEY_V2" in editor_df.columns:
        _editor_cols.insert(2, "JOB_KEY_V2")
    _editor_cols.insert(_editor_cols.index("Posted") + 1, "Listing")
    _editor_cols.insert(_editor_cols.index("Listing") + 1, "Age")
    return editor_df[[c for c in _editor_cols if c in editor_df.columns]]


def _render_recommended_actions(dashboard_df: pd.DataFrame) -> None:
    render_recommended_actions_section(dashboard_df)


def _render_job_search_progression(dashboard_df: pd.DataFrame) -> None:
    st.markdown("---")
    render_section_heading(JOB_SEARCH_PROGRESSION_TITLE)

    if dashboard_df.empty:
        st.caption("No visible jobs in the dashboard cohort.")
        return

    counts = compute_progression_funnel_counts(dashboard_df)
    render_job_search_progression_workflow(counts)


def _render_recruiter_relationship_progression(recruiter_crm_df: pd.DataFrame) -> None:
    render_subsection_heading(RECRUITER_RELATIONSHIP_PROGRESSION_TITLE)

    if recruiter_crm_df.empty:
        st.caption("No recruiters in the CRM cohort.")
        return

    counts = compute_recruiter_progression_counts(recruiter_crm_df)
    render_recruiter_relationship_progression_workflow(counts)


def _render_pipeline_analytics(editor_df: pd.DataFrame) -> None:
    st.markdown("---")
    with st.expander("PIPELINE ANALYTICS", expanded=False):
        pipeline_counts = editor_df["Status"].value_counts()
        total_applied = int(pipeline_counts.get("Applied", 0))
        total_interviews = int(
            pipeline_counts.get("Interview", 0) + pipeline_counts.get("Final Round", 0)
        )
        total_offers = int(pipeline_counts.get("Offer", 0))
        total_rejected = int(pipeline_counts.get("Rejected", 0))

        analytics_col1, analytics_col2, analytics_col3, analytics_col4 = st.columns(4)
        analytics_col1.metric("Applied", total_applied)
        analytics_col2.metric("Interviews", total_interviews)
        analytics_col3.metric("Offers", total_offers)
        analytics_col4.metric("Rejected", total_rejected)

        if editor_df.empty:
            st.caption("No visible jobs in the dashboard cohort.")
            return

        _source_group_col = (
            "source_key" if "source_key" in editor_df.columns else "Source"
        )
        source_summary_df = (
            editor_df.groupby(_source_group_col)
            .agg(
                jobs=("JOB_KEY", "count"),
                interviews=("Status", lambda x: (x == "Interview").sum()),
                offers=("Status", lambda x: (x == "Offer").sum()),
                rejections=("Status", lambda x: (x == "Rejected").sum()),
            )
            .reset_index()
        )
        source_summary_df["Source"] = source_summary_df[_source_group_col].map(
            source_display_name
        )
        source_summary_df = source_summary_df.drop(columns=[_source_group_col])
        source_summary_df["Interview Rate"] = (
            (source_summary_df["interviews"] / source_summary_df["jobs"]) * 100
        ).round(1)
        source_summary_df["Offer Rate"] = (
            (source_summary_df["offers"] / source_summary_df["jobs"]) * 100
        ).round(1)
        source_summary_df["Rejection Rate"] = (
            (source_summary_df["rejections"] / source_summary_df["jobs"]) * 100
        ).round(1)
        source_summary_df = source_summary_df.rename(
            columns={
                "jobs": "Jobs",
                "interviews": "Interviews",
                "offers": "Offers",
                "rejections": "Rejections",
            }
        )
        source_summary_df = source_summary_df[
            [
                "Source",
                "Jobs",
                "Interviews",
                "Offers",
                "Rejections",
                "Interview Rate",
                "Offer Rate",
                "Rejection Rate",
            ]
        ]

        st.subheader("SOURCE EFFECTIVENESS")
        st.dataframe(source_summary_df, width="stretch", hide_index=True)


@st.cache_data
def load_data(use_sqlite: bool, jobs_csv_mtime: float, db_mtime: float):
    return load_dashboard_jobs_df()


@st.cache_data
def load_historical_state(
    use_sqlite: bool, jobs_csv_mtime: float, db_mtime: float, historical_csv_mtime: float
):
    return load_dashboard_historical_df()


st.set_page_config(page_title=PRODUCT_TITLE, layout="wide")

reset_loader_diagnostics()
_use_sqlite = dashboard_read_enabled()
_jobs_mtime = _path_mtime(paths.jobs_csv())
_db_mtime = _path_mtime(paths.jobs_db())
_hist_mtime = _path_mtime(paths.historical_jobs_csv())

latest_acquisition_df = load_data(_use_sqlite, _jobs_mtime, _db_mtime)
historical_state_df = load_historical_state(
    _use_sqlite, _jobs_mtime, _db_mtime, _hist_mtime
)
recruiter_crm_df = load_recruiter_crm_df()
outreach_df = load_outreach_df()

historical_state_df = _normalize_historical_state(historical_state_df)

dashboard_df = build_dashboard_df(historical_state_df)
_table_base_count = len(dashboard_df)

# =========================
# SIDEBAR
# =========================
st.sidebar.header("Filters")

_diag = get_loader_diagnostics()
_any_fallback = bool(
    _diag.get("jobs_csv_fallback_rows")
    or _diag.get("historical_full_csv_fallback")
    or _diag.get("crm_full_csv_fallback")
)
if dashboard_read_enabled():
    if _any_fallback:
        st.sidebar.info("Connected — some data from backup files")
    else:
        st.sidebar.success("Database connected")
else:
    st.sidebar.warning("Using saved export files")

date_field_label = st.sidebar.radio(
    "Date field",
    ["Posted", "Last Seen", "First Seen"],
    index=0,
    horizontal=True,
)
if date_field_label == "Posted":
    date_column = "posted_at_date"
elif date_field_label == "Last Seen":
    date_column = "last_seen"
else:
    date_column = "first_seen"

date_preset = st.sidebar.selectbox("Date range", DATE_RANGE_PRESETS, index=0)
custom_start = custom_end = None
if date_preset == "Custom":
    _today = date.today()
    _default_start = _today - timedelta(days=30)
    _picked = st.sidebar.date_input(
        "Custom dates",
        value=(_default_start, _today),
    )
    if isinstance(_picked, tuple) and len(_picked) == 2:
        custom_start, custom_end = _picked
    elif _picked:
        custom_start = custom_end = _picked

locations = ["All"] + sorted(
    dashboard_df["location"].dropna().unique().tolist()
)
selected_location = st.sidebar.selectbox("Location", locations)

sources = sorted(dashboard_df["source"].dropna().unique().tolist())
selected_sources = st.sidebar.multiselect(
    "Source",
    sources,
    default=sources,
    format_func=source_display_name,
)

selected_statuses = st.sidebar.multiselect(
    "Job Status",
    PIPELINE_STAGES,
    default=PIPELINE_STAGES,
)

min_score = st.sidebar.slider("Minimum Score", 0, 10, 0)
st.sidebar.caption("Minimum score applies to New and Saved jobs only.")

recruiter_only = st.sidebar.checkbox("Has recruiter contact", value=False)

# =========================
# APPLY SIDEBAR FILTERS (TABLE / LIST VIEWS ONLY)
# =========================
_filter_state = SidebarFilterState(
    date_column=date_column,
    date_preset=date_preset,
    custom_start=custom_start if date_preset == "Custom" else None,
    custom_end=custom_end if date_preset == "Custom" else None,
    selected_location=selected_location,
    selected_sources=tuple(selected_sources),
    selected_statuses=tuple(selected_statuses),
    min_score=min_score,
    recruiter_only=recruiter_only,
)
filtered_df = sort_for_table(apply_sidebar_filters(dashboard_df, _filter_state))

dashboard_editor_df = _build_editor_df(dashboard_df, historical_state_df)
editor_df = _build_editor_df(filtered_df, historical_state_df)
_last_refresh_label = load_last_data_refresh_label(
    _use_sqlite, _db_mtime, _jobs_mtime
)
_last_monitoring_label = load_last_monitoring_refresh_label(_use_sqlite, _db_mtime)

if "applied_jobs" not in st.session_state:
    st.session_state.applied_jobs = set()

# =========================
# HEADER
# =========================
inject_dashboard_help_css()
st.title(PRODUCT_TITLE)
render_refresh_labels_row(_last_refresh_label, _last_monitoring_label)

col1, col2, col3 = st.columns(3)
col1.metric("Total Jobs", len(dashboard_df))
col2.metric("Latest Acquisition", len(latest_acquisition_df))
col3.metric("Total Recruiters", len(recruiter_crm_df))

# =========================
# RECOMMENDED ACTIONS
# =========================
_render_recommended_actions(dashboard_df)

# =========================
# SOURCE DISTRIBUTION
# =========================
st.markdown("---")
render_section_heading("Source Distribution")

if dashboard_df.empty:
    st.caption("No visible jobs in the dashboard cohort.")
else:
    source_counts = (
        dashboard_df["source"]
        .value_counts()
        .reset_index()
    )
    source_counts.columns = ["source", "count"]
    source_counts["source_label"] = source_counts["source"].map(source_display_name)
    source_chart = (
        alt.Chart(source_counts)
        .mark_bar()
        .encode(
            y=alt.Y(
                "source_label:N",
                sort=alt.EncodingSortField(field="count", order="descending"),
                title="Source",
            ),
            x=alt.X("count:Q", title="Jobs"),
            tooltip=[
                alt.Tooltip("source_label:N", title="Source"),
                alt.Tooltip("count:Q", title="Jobs"),
            ],
            color=alt.Color("source_label:N", legend=None),
        )
    )
    st.altair_chart(source_chart, width="stretch")

# =========================
# PIPELINE ANALYTICS
# =========================
_render_pipeline_analytics(dashboard_editor_df)

# =========================
# JOB SEARCH PROGRESSION
# =========================
_render_job_search_progression(dashboard_df)

# =========================
# JOB LISTINGS
# =========================
st.markdown("---")
render_subheader_with_help(
    "Job Listings",
    "Editing Hiring Manager updates the recruiter shown for this job.",
    "Recruiter CRM retains historical recruiter relationships for the role.",
)
if not dashboard_write_enabled():
    st.info(
        "Hiring Manager enrichment requires SQLite dashboard writes "
        "(SQLITE_DASHBOARD_WRITE=1)."
    )
_filtered_count = len(filtered_df)
if _filtered_count < _table_base_count:
    st.caption(f"Showing {_filtered_count:,} of {_table_base_count:,} jobs")

if "stable_editor_df" not in st.session_state:
    st.session_state.stable_editor_df = editor_df.copy()

_job_column_order = [
    "#",
    "Title",
    "Company",
    "Location",
    "Posted",
    "Hiring Manager",
    "AI Score",
    "Reason",
    "Source",
    "Link",
    "Status",
    "Notes",
]
_job_column_config = {
    "JOB_KEY": None,
    "JOB_KEY_V2": None,
    "source_key": None,
    "#": st.column_config.NumberColumn("#", width="small", disabled=True),
    "Title": st.column_config.TextColumn("Title", width="large"),
    "Company": st.column_config.TextColumn("Company", width="medium"),
    "Location": st.column_config.TextColumn("Location", width="medium"),
    "Hiring Manager": st.column_config.TextColumn(
        "Hiring Manager", width="medium"
    ),
    "Posted": st.column_config.TextColumn("Posted", width="small"),
    "AI Score": st.column_config.TextColumn("AI Score", width="small"),
    "Reason": st.column_config.TextColumn("Reason", width="medium"),
    "Source": st.column_config.TextColumn("Source", width="small"),
    "Link": st.column_config.LinkColumn("Link", width="medium"),
    "Status": st.column_config.SelectboxColumn(
        "Status",
        options=PIPELINE_STAGES,
        width="medium",
    ),
    "Notes": st.column_config.TextColumn("Notes", width="large"),
}
_job_disabled_columns = [
    "#",
    "Title",
    "Company",
    "Location",
    "Posted",
    "AI Score",
    "Source",
    "Link",
]
_job_column_order.insert(_job_column_order.index("Posted") + 1, "Listing")
_job_column_order.insert(_job_column_order.index("Listing") + 1, "Age")
_job_column_config["Listing"] = st.column_config.TextColumn(
    "Listing",
    width="small",
    disabled=True,
)
_job_column_config["Age"] = st.column_config.TextColumn(
    "Age", width="small", disabled=True
)
_job_column_config["listing_status"] = None
_job_disabled_columns.extend(["Listing", "Age", "listing_status"])

_open_editor_df, _closed_editor_df = partition_editor_df_by_listing(
    editor_df,
    listing_visibility_enabled=True,
)

_closed_listings_column_config = closed_listings_readonly_column_config(_job_column_config)

def _render_closed_listings_table(closed_df: pd.DataFrame) -> None:
    display_columns = [col for col in _job_column_order if col in closed_df.columns]
    st.dataframe(
        style_closed_listings_display_df(closed_df),
        width="stretch",
        height=min(400, 35 * len(closed_df) + 38),
        hide_index=True,
        column_order=display_columns,
        column_config=_closed_listings_column_config,
    )


edited_open_df = _open_editor_df.copy()

if _open_editor_df.empty:
    st.caption("No actionable job listings match the current filters.")
else:
    edited_open_df = st.data_editor(
        _open_editor_df,
        key="job_table_editor",
        num_rows="fixed",
        width="stretch",
        height=600,
        hide_index=True,
        column_order=_job_column_order,
        column_config=_job_column_config,
        disabled=_job_disabled_columns,
    )

_job_editor_dirty = False
if not _open_editor_df.empty:
    _job_editor_dirty = job_editor_return_differs_input(_open_editor_df, edited_open_df)

st.markdown("---")
render_subheader_with_help(
    CLOSED_LISTINGS_SECTION_TITLE,
    CLOSED_LISTING_READONLY_HELP,
)
if _closed_editor_df.empty:
    st.caption("No closed listings match the current filters.")
else:
    _render_closed_listings_table(_closed_editor_df)

updated_states = []
for _, row in edited_open_df.iterrows():
    pipeline_stage = str(row["Status"]).strip()
    applied_state = pipeline_stage in [
        "Applied",
        "HR Screen",
        "Interview",
        "Final Round",
        "Offer",
    ]
    interview_state = pipeline_stage in ["Interview", "Final Round", "Offer"]
    offer_state = pipeline_stage == "Offer"
    rejected_state = pipeline_stage == "Rejected"
    _state = {
        "JOB_KEY": str(row["JOB_KEY"]).strip(),
        "pipeline_stage": pipeline_stage,
        "applied": applied_state,
        "rejected": rejected_state,
        "interview": interview_state,
        "offer": offer_state,
        "notes": str(row["Notes"]),
        "hiring_manager": str(row["Hiring Manager"]),
        "company": str(row.get("Company", "") or ""),
        "source": str(row.get("source_key", "") or row.get("Source", "") or ""),
    }
    if "JOB_KEY_V2" in row.index:
        _state["JOB_KEY_V2"] = str(row["JOB_KEY_V2"]).strip()
    updated_states.append(_state)

updated_states = filter_persisted_job_states(
    updated_states,
    editor_df,
    listing_visibility_enabled=True,
)

updated_df = pd.DataFrame(updated_states)

if dashboard_write_enabled():
    _job_rows_persisted = persist_dashboard_job_edits(
        updated_df,
        prior_df=_open_editor_df,
    )
    if _job_rows_persisted and _job_editor_dirty:
        st.toast("Changes saved", icon="✅")
else:
    historical_df = pd.read_csv(str(paths.historical_jobs_csv()))
    historical_df["JOB_KEY"] = historical_df["JOB_KEY"].astype(str).str.strip()
    updated_df["JOB_KEY"] = updated_df["JOB_KEY"].astype(str).str.strip()

    required_cols = {
        "pipeline_stage": "New",
        "applied": False,
        "rejected": False,
        "interview": False,
        "offer": False,
        "notes": "",
    }
    for col, default_value in required_cols.items():
        if col not in historical_df.columns:
            historical_df[col] = default_value

    for col in ("pipeline_stage", "notes"):
        historical_df[col] = historical_df[col].fillna("").astype(str)
    for col in ("applied", "rejected", "interview", "offer"):
        historical_df[col] = historical_df[col].fillna(False).astype(bool)

    historical_df = _ensure_merge_key_columns(historical_df)
    updated_df = _ensure_merge_key_columns(updated_df)
    historical_df = historical_df.set_index("__merge_key")
    update_index = updated_df.set_index("__merge_key")
    matched_keys = update_index.index.intersection(historical_df.index)
    for col in required_cols:
        historical_df.loc[matched_keys, col] = update_index.loc[matched_keys, col]
    historical_df = historical_df.reset_index()
    historical_df = historical_df.drop(columns=["response_status"], errors="ignore")
    historical_df.to_csv(str(paths.historical_jobs_csv()), index=False)
    if _job_editor_dirty:
        st.toast("Changes saved", icon="✅")

# =========================
# RECRUITER RELATIONSHIP MANAGEMENT
# =========================
st.markdown("---")
render_subheader_with_help(
    "Recruiter Relationship Management",
    "Track recruiter relationship stages and job connections over time.",
    "Total Recruiters is shown in the dashboard header above.",
)
_render_recruiter_relationship_progression(recruiter_crm_df)

display_crm_df = recruiter_crm_df.copy()
display_crm_df.insert(0, "#", range(1, len(display_crm_df) + 1))
display_crm_df["source_key"] = (
    display_crm_df["source"].fillna("").astype(str).str.strip()
)

crm_editor_df = display_crm_df[
    [
        "#",
        "RECRUITER_KEY",
        "recruiter_name",
        "current_company",
        "source",
        "first_seen",
        "last_seen",
        "jobs_connected",
        "recruiter_stage",
        "source_key",
    ]
].rename(
    columns={
        "recruiter_name": "Recruiter",
        "current_company": "Company",
        "first_seen": "First Seen",
        "last_seen": "Last Seen",
        "jobs_connected": "Jobs Connected",
        "recruiter_stage": "Status",
    }
)
crm_editor_df["First Seen"] = crm_editor_df["First Seen"].map(format_dashboard_date)
crm_editor_df["Last Seen"] = crm_editor_df["Last Seen"].map(format_dashboard_date)
crm_editor_df["Source"] = crm_editor_df["source_key"].map(source_display_name)

edited_crm_df = st.data_editor(
    crm_editor_df,
    key="recruiter_crm_editor",
    width="stretch",
    height=400,
    hide_index=True,
    column_order=[
        "#",
        "Recruiter",
        "Company",
        "Source",
        "First Seen",
        "Last Seen",
        "Jobs Connected",
        "Status",
    ],
    column_config={
        "RECRUITER_KEY": None,
        "source_key": None,
        "#": st.column_config.NumberColumn("#", width="small", disabled=True),
        "Recruiter": st.column_config.TextColumn("Recruiter", disabled=True),
        "Company": st.column_config.TextColumn("Company", disabled=True),
        "Source": st.column_config.TextColumn("Source", disabled=True),
        "First Seen": st.column_config.TextColumn("First Seen", disabled=True),
        "Last Seen": st.column_config.TextColumn("Last Seen", disabled=True),
        "Jobs Connected": st.column_config.NumberColumn(
            "Jobs Connected", disabled=True
        ),
        "Status": st.column_config.SelectboxColumn(
            "Status",
            options=CRM_STATUS_OPTIONS,
            width="medium",
        ),
    },
)

if dashboard_write_enabled():
    persist_dashboard_crm_edits(
        edited_crm_df["RECRUITER_KEY"].astype(str).tolist(),
        edited_crm_df["Status"].astype(str).tolist(),
    )
else:
    crm_save_df = recruiter_crm_df.copy()
    crm_save_df["recruiter_stage"] = edited_crm_df["Status"].values
    crm_save_df.to_csv(str(paths.recruiter_crm_csv()), index=False)

if _job_editor_dirty:
    st.rerun()

# =========================
# OUTREACH INTELLIGENCE
# =========================
render_outreach_intelligence_section(
    outreach_df=outreach_df,
    editor_df=dashboard_editor_df,
    reference_date=date.today(),
    write_enabled=dashboard_write_enabled(),
)

# =========================
# OPERATIONAL CONTROLS
# =========================
render_operational_controls_section()

# =========================
# ACQUISITION HEALTH
# =========================
render_acquisition_health_section()

# =========================
# OPERATIONAL MONITOR HEALTH
# =========================
render_operational_monitor_health_section(dashboard_df)

# =========================
# AI REFRESH HEALTH
# =========================
render_ai_refresh_health_section()
