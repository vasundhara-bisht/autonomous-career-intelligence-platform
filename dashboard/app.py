import streamlit as st
import pandas as pd
import altair as alt
from datetime import date, datetime, timedelta

import paths
from db.read.engine import dashboard_read_enabled, dashboard_write_enabled
from db.services.dashboard_write import (
    persist_dashboard_crm_edits,
    persist_dashboard_job_edits,
)
from loaders import (
    apply_historical_display_columns,
    get_loader_diagnostics,
    load_dashboard_historical_df,
    load_dashboard_jobs_df,
    load_recruiter_crm_df,
    reset_loader_diagnostics,
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


def _parse_dashboard_datetime(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, errors="coerce")


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


def _merge_pipeline_stage(display_base: pd.DataFrame, historical: pd.DataFrame) -> pd.DataFrame:
    """Attach pipeline_stage for sidebar Status filter (UI-only merge)."""
    hist = _ensure_merge_key_columns(historical)
    stage_cols = ["__merge_key", "pipeline_stage"]
    if "pipeline_stage" not in hist.columns:
        hist["pipeline_stage"] = "New"

    out = _ensure_merge_key_columns(display_base)
    out = out.merge(hist[stage_cols], on="__merge_key", how="left")
    out["pipeline_stage"] = out["pipeline_stage"].fillna("New")
    return out.drop(columns=["__merge_key"], errors="ignore")


def _apply_date_range_filter(
    df: pd.DataFrame,
    *,
    date_column: str,
    preset: str,
    custom_start,
    custom_end,
) -> pd.DataFrame:
    if preset == "All time" or date_column not in df.columns:
        return df

    parsed = _parse_dashboard_datetime(df[date_column])
    today = pd.Timestamp.now().normalize()

    if preset == "Last 7 days":
        start = today - pd.Timedelta(days=7)
        end = today + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
    elif preset == "Last 30 days":
        start = today - pd.Timedelta(days=30)
        end = today + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
    elif preset == "Custom":
        if not custom_start or not custom_end:
            return df
        start = pd.Timestamp(custom_start).normalize()
        end = pd.Timestamp(custom_end).normalize() + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
    else:
        return df

    mask = parsed.notna() & (parsed >= start) & (parsed <= end)
    return df.loc[mask].copy()


def score_badge(score, ai_status):
    if str(ai_status or "").lower() != "scored":
        return "Pending AI"
    if score >= 9:
        return f"🟢 {score}"
    if score >= 7:
        return f"🟡 {score}"
    return f"🔴 {score}"


def _job_editor_return_differs_input(before_df, after_df):
    cols = ["Status", "Notes"]
    for c in cols:
        if c not in before_df.columns or c not in after_df.columns:
            continue
        a = (
            before_df[c]
            .fillna("")
            .astype(str)
            .str.strip()
            .reset_index(drop=True)
        )
        b = (
            after_df[c]
            .fillna("")
            .astype(str)
            .str.strip()
            .reset_index(drop=True)
        )
        if not a.equals(b):
            return True
    return False


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
    editor_df["ai_score_display"] = editor_df.apply(
        lambda row: score_badge(row["score"], row.get("ai_status")),
        axis=1,
    )
    editor_df["reason"] = editor_df["reason"].astype(str).str.slice(0, 120)
    editor_df = editor_df.rename(
        columns={
            "title": "Title",
            "company": "Company",
            "location": "Location",
            "time_posted": "Posted",
            "hiring_manager": "Hiring Manager",
            "ai_score_display": "AI Score",
            "reason": "Reason",
            "source": "Source",
            "link": "Link",
            "pipeline_stage": "Status",
            "notes": "Notes",
        }
    )
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
        "Source",
        "Link",
        "Status",
        "Notes",
    ]
    if "JOB_KEY_V2" in editor_df.columns:
        _editor_cols.insert(2, "JOB_KEY_V2")
    return editor_df[[c for c in _editor_cols if c in editor_df.columns]]


def _render_pipeline_analytics(editor_df: pd.DataFrame) -> None:
    st.markdown("---")
    with st.expander("Pipeline analytics", expanded=False):
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
            st.caption("No jobs match the current filters.")
            return

        source_summary_df = (
            editor_df.groupby("Source")
            .agg(
                jobs=("JOB_KEY", "count"),
                interviews=("Status", lambda x: (x == "Interview").sum()),
                offers=("Status", lambda x: (x == "Offer").sum()),
                rejections=("Status", lambda x: (x == "Rejected").sum()),
            )
            .reset_index()
        )
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

        st.subheader("Source Effectiveness")
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

historical_state_df = _normalize_historical_state(historical_state_df)

historical_display_df = apply_historical_display_columns(historical_state_df.copy())
if "currently_active" in historical_display_df.columns:
    historical_display_df = historical_display_df[
        historical_display_df["currently_active"] == True
    ]

if "pipeline_stage" not in historical_display_df.columns:
    historical_display_df = _merge_pipeline_stage(
        historical_display_df, historical_state_df
    )
else:
    historical_display_df["pipeline_stage"] = (
        historical_display_df["pipeline_stage"].fillna("New").astype(str).str.strip()
    )
_table_base_count = len(historical_display_df)

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
    ["Last Seen", "First Seen"],
    index=0,
    horizontal=True,
)
date_column = "last_seen" if date_field_label == "Last Seen" else "first_seen"

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
    historical_display_df["location"].dropna().unique().tolist()
)
selected_location = st.sidebar.selectbox("Location", locations)

sources = sorted(historical_display_df["source"].dropna().unique().tolist())
selected_sources = st.sidebar.multiselect("Source", sources, default=sources)

selected_statuses = st.sidebar.multiselect(
    "Status",
    PIPELINE_STAGES,
    default=PIPELINE_STAGES,
)

min_score = st.sidebar.slider("Minimum Score", 0, 10, 0)

recruiter_only = st.sidebar.checkbox("Has recruiter contact", value=False)

# =========================
# APPLY FILTERS
# =========================
filtered_df = historical_display_df.copy()

filtered_df = _apply_date_range_filter(
    filtered_df,
    date_column=date_column,
    preset=date_preset,
    custom_start=custom_start if date_preset == "Custom" else None,
    custom_end=custom_end if date_preset == "Custom" else None,
)

if selected_location != "All":
    filtered_df = filtered_df[filtered_df["location"] == selected_location]

if selected_sources:
    filtered_df = filtered_df[filtered_df["source"].isin(selected_sources)]

if selected_statuses:
    filtered_df = filtered_df[filtered_df["pipeline_stage"].isin(selected_statuses)]

filtered_df = filtered_df[
    (filtered_df["is_ai_scored"]) & (filtered_df["score"] >= min_score)
]

if recruiter_only:
    filtered_df = filtered_df[filtered_df["hiring_manager"] != "Not Specified"]

filtered_df = filtered_df.sort_values(
    by=["is_ai_scored", "score", "JOB_KEY"],
    ascending=[False, False, True],
)

editor_df = _build_editor_df(filtered_df, historical_state_df)
_last_refresh_label = load_last_data_refresh_label(
    _use_sqlite, _db_mtime, _jobs_mtime
)

if "applied_jobs" not in st.session_state:
    st.session_state.applied_jobs = set()

# =========================
# HEADER
# =========================
st.title(PRODUCT_TITLE)
st.caption(f"Last refresh: {_last_refresh_label}")

col1, col2, col3 = st.columns(3)
col1.metric("Total Jobs", len(historical_state_df))
col2.metric("Latest Acquisition", len(latest_acquisition_df))
col3.metric("Total Recruiters", len(recruiter_crm_df))

# =========================
# SOURCE DISTRIBUTION
# =========================
st.markdown("---")
st.subheader("Source Distribution")

if filtered_df.empty:
    st.caption("No jobs match the current filters.")
else:
    source_counts = (
        filtered_df["source"]
        .value_counts()
        .reset_index()
    )
    source_counts.columns = ["source", "count"]
    source_chart = (
        alt.Chart(source_counts)
        .mark_bar()
        .encode(
            y=alt.Y("source:N", sort="-x", title="Source"),
            x=alt.X("count:Q", title="Jobs"),
            tooltip=["source", "count"],
            color=alt.Color("source:N", legend=None),
        )
    )
    st.altair_chart(source_chart, width="stretch")

# =========================
# PIPELINE ANALYTICS
# =========================
_render_pipeline_analytics(editor_df)

# =========================
# JOB LISTINGS
# =========================
st.markdown("---")
st.subheader("Job Listings")
_filtered_count = len(filtered_df)
if _filtered_count < _table_base_count:
    st.caption(f"Showing {_filtered_count:,} of {_table_base_count:,} jobs")

if "stable_editor_df" not in st.session_state:
    st.session_state.stable_editor_df = editor_df.copy()

edited_df = st.data_editor(
    editor_df,
    key="job_table_editor",
    num_rows="fixed",
    width="stretch",
    height=600,
    hide_index=True,
    column_order=[
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
    ],
    column_config={
        "JOB_KEY": None,
        "JOB_KEY_V2": None,
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
    },
    disabled=[
        "#",
        "Title",
        "Company",
        "Location",
        "Posted",
        "AI Score",
        "Link",
    ],
)

_job_editor_dirty = _job_editor_return_differs_input(editor_df, edited_df)

updated_states = []
for _, row in edited_df.iterrows():
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
    }
    if "JOB_KEY_V2" in row.index:
        _state["JOB_KEY_V2"] = str(row["JOB_KEY_V2"]).strip()
    updated_states.append(_state)

updated_df = pd.DataFrame(updated_states)

if dashboard_write_enabled():
    _job_rows_persisted = persist_dashboard_job_edits(updated_df)
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
# RECRUITER RELATIONSHIP MANAGER
# =========================
st.markdown("---")
st.subheader("Recruiter Relationship Manager")

crm_col1, crm_col2 = st.columns(2)
crm_col1.metric(
    "Active Recruiters",
    int(recruiter_crm_df[recruiter_crm_df["currently_active"] == True].shape[0]),
)
crm_col2.metric(
    "Recruiters Replied",
    int(recruiter_crm_df[recruiter_crm_df["recruiter_replied"] == True].shape[0]),
)

display_crm_df = recruiter_crm_df.copy()
display_crm_df.insert(0, "#", range(1, len(display_crm_df) + 1))

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
    ]
].rename(
    columns={
        "recruiter_name": "Recruiter",
        "current_company": "Company",
        "source": "Source",
        "first_seen": "First Seen",
        "last_seen": "Last Seen",
        "jobs_connected": "Jobs Connected",
        "recruiter_stage": "Status",
    }
)

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
            options=[
                "discovered",
                "warm",
                "active",
                "responded",
                "ghosted",
                "archived",
            ],
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
