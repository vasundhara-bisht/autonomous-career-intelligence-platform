import streamlit as st
import pandas as pd
import altair as alt

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

st.set_page_config(page_title="AI Job Dashboard", layout="wide")


# =========================
# UI-ONLY LOCATION / WORK-MODE HEURISTICS
# =========================
def _classify_location_bucket(location: object) -> str:
    """Keyword bucket for dashboard charts (not a geo engine)."""
    s = str(location or "").lower().strip()
    if not s or s in ("unknown", "nan", "not specified"):
        return "Other"
    if any(
        k in s
        for k in (
            "remote",
            "wfh",
            "work from home",
            "work-from-home",
            "anywhere",
            "distributed",
        )
    ):
        return "Remote"
    if "singapore" in s:
        return "Singapore"
    if any(
        k in s
        for k in (
            "united states",
            "usa",
            "u.s.a",
            "new york",
            "san francisco",
            "california",
            "seattle",
            "austin",
            "boston",
            "chicago",
            "texas",
            "washington dc",
        )
    ) or s in ("us", "usa"):
        return "US"
    if any(
        k in s
        for k in (
            "india",
            "bangalore",
            "bengaluru",
            "mumbai",
            "delhi",
            "hyderabad",
            "pune",
            "chennai",
            "kolkata",
            "gurgaon",
            "gurugram",
            "noida",
            "karnataka",
            "maharashtra",
        )
    ):
        return "India"
    if any(
        k in s
        for k in (
            "europe",
            "uk",
            "united kingdom",
            "london",
            "berlin",
            "paris",
            "amsterdam",
            "dublin",
            "germany",
            "france",
            "spain",
            "netherlands",
            "stockholm",
            "munich",
        )
    ):
        return "Europe"
    if any(
        k in s
        for k in (
            "apac",
            "australia",
            "sydney",
            "melbourne",
            "japan",
            "tokyo",
            "korea",
            "hong kong",
            "malaysia",
            "indonesia",
            "philippines",
            "thailand",
            "vietnam",
            "new zealand",
            "taiwan",
            "china",
            "beijing",
            "shanghai",
        )
    ):
        return "APAC"
    return "Other"


def _classify_work_mode(location: object) -> str:
    """Remote / hybrid / onsite heuristic from LOCATION text."""
    s = str(location or "").lower().strip()
    if "hybrid" in s:
        return "Hybrid"
    if any(
        k in s
        for k in ("remote", "wfh", "work from home", "work-from-home", "anywhere")
    ):
        return "Remote"
    if any(
        k in s
        for k in ("onsite", "on-site", "on site", "in-office", "in office", "on-prem")
    ):
        return "Onsite"
    return "Onsite"


# =========================
# LOAD DATA
# =========================
def _path_mtime(path) -> float:
    return path.stat().st_mtime if path.is_file() else 0.0


@st.cache_data
def load_data(use_sqlite: bool, jobs_csv_mtime: float, db_mtime: float):
    return load_dashboard_jobs_df()


@st.cache_data
def load_historical_state(
    use_sqlite: bool, jobs_csv_mtime: float, db_mtime: float, historical_csv_mtime: float
):
    return load_dashboard_historical_df()


reset_loader_diagnostics()
_use_sqlite = dashboard_read_enabled()
_jobs_mtime = _path_mtime(paths.jobs_csv())
_db_mtime = _path_mtime(paths.jobs_db())
_hist_mtime = _path_mtime(paths.historical_jobs_csv())

df = load_data(_use_sqlite, _jobs_mtime, _db_mtime)
historical_state_df = load_historical_state(
    _use_sqlite, _jobs_mtime, _db_mtime, _hist_mtime
)

# =========================
# LOAD RECRUITER CRM
# =========================
recruiter_crm_df = load_recruiter_crm_df()

# =========================
# HISTORICAL DISPLAY DATA
# =========================

historical_display_df = apply_historical_display_columns(historical_state_df.copy())

# Keep only active jobs for now
if "currently_active" in historical_display_df.columns:

    historical_display_df = historical_display_df[
        historical_display_df["currently_active"] == True
    ]

# =========================
# SIDEBAR FILTERS
# =========================
st.sidebar.header("Filters")

if dashboard_read_enabled():
    _diag = get_loader_diagnostics()
    _fallback_note = ""
    if _diag.get("jobs_csv_fallback_rows"):
        _fallback_note = (
            f" ({_diag['jobs_csv_fallback_rows']} jobs.csv row fallback)"
        )
    if _diag.get("historical_full_csv_fallback"):
        _fallback_note += " (historical CSV fallback)"
    if _diag.get("crm_full_csv_fallback"):
        _fallback_note += " (CRM CSV fallback)"
    st.sidebar.caption(
        f"Data source: SQLite (SQLITE_READ=1){_fallback_note}"
    )

if dashboard_write_enabled():
    st.sidebar.caption("Edits persist to SQLite (SQLITE_DASHBOARD_WRITE=1)")

locations = ["All"] + sorted(
    historical_display_df["location"]
    .dropna()
    .unique()
    .tolist()
)

selected_location = st.sidebar.selectbox(
    "Location",
    locations
)

sources = sorted(
    historical_display_df["source"]
    .dropna()
    .unique()
    .tolist()
)

selected_sources = st.sidebar.multiselect(
    "Source",
    sources,
    default=sources
)

min_score = st.sidebar.slider(
    "Minimum Score",
    0,
    10,
    0
)

include_pending_ai = st.sidebar.checkbox(
    "Include pending AI rows",
    value=False
)

recruiter_only = st.sidebar.checkbox(
    "Only show jobs with recruiter",
    value=False
)

# =========================
# APPLY FILTERS
# =========================
filtered_df = historical_display_df.copy()

if selected_location != "All":
    filtered_df = filtered_df[filtered_df["location"] == selected_location]

filtered_df = filtered_df[filtered_df["source"].isin(selected_sources)]
if include_pending_ai:
    filtered_df = filtered_df[
        ((filtered_df["is_ai_scored"]) & (filtered_df["score"] >= min_score))
        | (~filtered_df["is_ai_scored"])
    ]
else:
    filtered_df = filtered_df[
        (filtered_df["is_ai_scored"]) & (filtered_df["score"] >= min_score)
    ]

if recruiter_only:
    filtered_df = filtered_df[filtered_df["hiring_manager"] != "Not Specified"]

filtered_df = filtered_df.sort_values(
    by=["is_ai_scored", "score", "JOB_KEY"],
    ascending=[False, False, True]
)

# =========================
# HEADER
# =========================
st.title("🚀 AI Job Dashboard")
st.caption(f"Last refreshed: {pd.Timestamp.now().strftime('%d %b %Y • %I:%M %p')}")

col1, col2, col3 = st.columns(3)
col1.metric("Total Jobs", len(df))
col2.metric("Visible Jobs", len(filtered_df))
col3.metric("Sources", filtered_df["source"].nunique())

# =========================
# CHARTS (MINIMAL)
# =========================
st.markdown("---")

st.subheader("🌍 Job Location Distribution")

_location_buckets = [
    "India",
    "Remote",
    "US",
    "Singapore",
    "Europe",
    "APAC",
    "Other",
]
location_counts = (
    filtered_df["location"]
    .map(_classify_location_bucket)
    .value_counts()
    .reindex(_location_buckets, fill_value=0)
    .reset_index()
)
location_counts.columns = ["region", "count"]

location_chart = (
    alt.Chart(location_counts)
    .mark_bar()
    .encode(
        y=alt.Y("region:N", sort=_location_buckets),
        x=alt.X("count:Q", title="Jobs"),
        tooltip=["region", "count"],
        color=alt.Color("region:N", legend=None),
    )
)

st.altair_chart(location_chart, width="stretch")

_work_modes = filtered_df["location"].map(_classify_work_mode)
mode_col1, mode_col2, mode_col3 = st.columns(3)
mode_col1.metric("Remote Jobs", int((_work_modes == "Remote").sum()))
mode_col2.metric("Hybrid Jobs", int((_work_modes == "Hybrid").sum()))
mode_col3.metric("Onsite Jobs", int((_work_modes == "Onsite").sum()))

# =========================
# TABLE (NO PAGINATION)
# =========================
st.markdown("---")
st.subheader("📋 Job Listings")

display_df = filtered_df.copy()
display_df["RAW_SCORE"] = display_df["score"]

# =========================
# CANONICAL JOB KEY
# =========================
display_df["JOB_KEY"] = (
    display_df["JOB_KEY"]
    .astype(str)
    .str.strip()
)

display_df.reset_index(drop=True, inplace=True)

# =========================
# LEGACY SESSION STATE
# =========================
if "applied_jobs" not in st.session_state:
    st.session_state.applied_jobs = set()

# =========================
# NORMALIZE HISTORICAL STATE
# =========================
historical_state_df["applied"] = (
    historical_state_df["applied"]
    .astype(str)
    .str.lower()
    .map({"true": True, "false": False})
    .fillna(False)
)

historical_state_df["rejected"] = (
    historical_state_df["rejected"]
    .astype(str)
    .str.lower()
    .map({"true": True, "false": False})
    .fillna(False)
)

# Normalize interview
historical_state_df["interview"] = (
    historical_state_df["interview"]
    .astype(str)
    .str.lower()
    .map({"true": True, "false": False})
    .fillna(False)
)

# Normalize offer
historical_state_df["offer"] = (
    historical_state_df["offer"]
    .astype(str)
    .str.lower()
    .map({"true": True, "false": False})
    .fillna(False)
)

# Normalize notes
historical_state_df["notes"] = (
    historical_state_df["notes"]
    .fillna("")
    .astype(str)
)

# =========================
# CANONICAL PIPELINE STATE
# =========================

# =====================================================
# 🧠 CANONICAL PIPELINE NORMALIZATION
# =====================================================

# Create column if missing
if "pipeline_stage" not in historical_state_df.columns:
    historical_state_df["pipeline_stage"] = "New"

# Normalize pipeline state
historical_state_df["pipeline_stage"] = (
    historical_state_df["pipeline_stage"]
    .fillna("New")
    .astype(str)
    .str.strip()
)

# =====================================================
# 🔄 DERIVE LEGACY STATES FROM PIPELINE_STAGE
# =====================================================

historical_state_df["applied"] = (
    historical_state_df["pipeline_stage"]
    .isin([
        "Applied",
        "HR Screen",
        "Interview",
        "Final Round",
        "Offer"
    ])
)

historical_state_df["interview"] = (
    historical_state_df["pipeline_stage"]
    .isin([
        "Interview",
        "Final Round",
        "Offer"
    ])
)

historical_state_df["offer"] = (
    historical_state_df["pipeline_stage"] == "Offer"
)

historical_state_df["rejected"] = (
    historical_state_df["pipeline_stage"] == "Rejected"
)

# Remove existing state columns before merge
display_df = display_df.drop(
    columns=[
        "applied",
        "rejected",
        "pipeline_stage",
        "interview",
        "offer",
        "notes",
        "response_status",
    ],
    errors="ignore"
)

# =========================
# MERGE HISTORICAL STATE
# =========================

# Merge pipeline state only; JOB_KEY / JOB_KEY_V2 stay on display_df (avoid _x/_y suffixes).
_hist_cols = [
    "applied",
    "rejected",
    "interview",
    "offer",
    "pipeline_stage",
    "notes",
]

display_df = _ensure_merge_key_columns(display_df)
historical_state_df = _ensure_merge_key_columns(historical_state_df)

display_df = display_df.merge(
    historical_state_df[[c for c in _hist_cols if c in historical_state_df.columns] + ["__merge_key"]],
    on="__merge_key",
    how="left",
)
display_df = display_df.drop(columns=["__merge_key"], errors="ignore")

# =========================
# ENSURE STATE COLUMNS EXIST
# =========================

state_defaults = {

    # Legacy checkbox states
    "applied": False,
    "rejected": False,
    "interview": False,
    "offer": False,

    # Canonical pipeline state
    "pipeline_stage": "New",

    # Recruiter metadata
    "notes": "",
}

for col, default_value in state_defaults.items():

    if col not in display_df.columns:
        display_df[col] = default_value

    display_df[col] = display_df[col].fillna(default_value)

# Force boolean types
display_df["applied"] = display_df["applied"].astype(bool)
display_df["rejected"] = display_df["rejected"].astype(bool)
display_df["interview"] = display_df["interview"].astype(bool)
display_df["offer"] = display_df["offer"].astype(bool)

display_df = display_df.loc[:, ~display_df.columns.duplicated()]

# Capitalize columns
display_df.columns = [col.upper() for col in display_df.columns]

# =========================
# HISTORICAL ANALYTICS
# =========================

st.markdown("---")
st.subheader("📊 Historical Analytics")

# =========================
# PIPELINE ANALYTICS
# =========================

pipeline_counts = (
    display_df["PIPELINE_STAGE"]
    .value_counts()
)
total_applied = int(
    pipeline_counts.get("Applied", 0)
)
total_interviews = int(
    pipeline_counts.get("Interview", 0)
    + pipeline_counts.get("Final Round", 0)
)
total_offers = int(
    pipeline_counts.get("Offer", 0)
)
total_rejected = int(
    pipeline_counts.get("Rejected", 0)
)
analytics_col1, analytics_col2, analytics_col3, analytics_col4 = st.columns(4)
analytics_col1.metric(
    "Applied",
    total_applied
)
analytics_col2.metric(
    "Interviews",
    total_interviews
)
analytics_col3.metric(
    "Offers",
    total_offers
)
analytics_col4.metric(
    "Rejected",
    total_rejected
)

# =========================
# SOURCE EFFECTIVENESS
# =========================

source_summary_df = (
    display_df.groupby("SOURCE")
    .agg(
        TOTAL_JOBS=("JOB_KEY", "count"),
        INTERVIEWS=(
            "PIPELINE_STAGE",
            lambda x: (x == "Interview").sum()
        ),
        OFFERS=(
            "PIPELINE_STAGE",
            lambda x: (x == "Offer").sum()
        ),
        REJECTIONS=(
            "PIPELINE_STAGE",
            lambda x: (x == "Rejected").sum()
        )
    )
    .reset_index()
)

source_summary_df["INTERVIEW_RATE"] = (
    (
        source_summary_df["INTERVIEWS"]
        / source_summary_df["TOTAL_JOBS"]
    ) * 100
).round(1)

source_summary_df["OFFER_RATE"] = (
    (
        source_summary_df["OFFERS"]
        / source_summary_df["TOTAL_JOBS"]
    ) * 100
).round(1)

source_summary_df["REJECTION_RATE"] = (
    (
        source_summary_df["REJECTIONS"]
        / source_summary_df["TOTAL_JOBS"]
    ) * 100
).round(1)

# =========================
# SOURCE EFFECTIVENESS UI
# =========================
st.markdown("---")
st.subheader("📡 Source Effectiveness")

st.dataframe(
    source_summary_df,
    width="stretch",
    hide_index=True
)

display_df = display_df.loc[:, ~display_df.columns.duplicated()]


def score_badge(score, ai_status):
    if str(ai_status or "").lower() != "scored":
        return "Pending AI"
    if score >= 9:
        return f"🟢 {score}"
    elif score >= 7:
        return f"🟡 {score}"
    return f"🔴 {score}"


# =========================
# STABLE EDITOR DATAFRAME
# =========================
editor_df = display_df.copy()

editor_df["SCORE"] = editor_df.apply(
    lambda row: score_badge(row["SCORE"], row.get("AI_STATUS")),
    axis=1,
)

editor_df = editor_df.drop(
    columns=["AI_SCORE"],
    errors="ignore"
)

editor_df = editor_df.rename(
    columns={"SCORE": "AI SCORE"}
)

editor_df.insert(0, "Sr. No", range(1, len(editor_df) + 1))

editor_df["REASON"] = (
    editor_df["REASON"]
    .astype(str)
    .str.slice(0, 120)
)

_editor_cols = [
    "Sr. No",
    "JOB_KEY",
    "TITLE",
    "COMPANY",
    "LOCATION",
    "TIME_POSTED",
    "HIRING_MANAGER",
    "AI SCORE",
    "AI_STATUS",
    "REASON",
    "SOURCE",
    "LINK",
    "PIPELINE_STAGE",
    "NOTES",
]
if "JOB_KEY_V2" in editor_df.columns:
    _editor_cols.insert(2, "JOB_KEY_V2")
editor_df = editor_df[[c for c in _editor_cols if c in editor_df.columns]]

# =========================
# SESSION STATE SNAPSHOT
# =========================

if "stable_editor_df" not in st.session_state:

    st.session_state.stable_editor_df = (
        editor_df.copy()
    )


# =========================
# DATA EDITOR
# =========================
edited_df = st.data_editor(
    editor_df,
    key="job_table_editor",
    num_rows="fixed",
    width="stretch",
    height=800,
    hide_index=True,
    column_order=[
        "Sr. No",
        "TITLE",
        "COMPANY",
        "LOCATION",
        "TIME_POSTED",
        "HIRING_MANAGER",
        "AI SCORE",
        "AI_STATUS",
        "REASON",
        "SOURCE",
        "LINK",
        "PIPELINE_STAGE",
        "NOTES",
    ],
    column_config={
        "JOB_KEY": None,
        "JOB_KEY_V2": None,

        "Sr. No": st.column_config.NumberColumn("Sr. No", width="small", disabled=True),
        "TITLE": st.column_config.TextColumn("TITLE", width="large"),
        "COMPANY": st.column_config.TextColumn("COMPANY", width="medium"),
        "LOCATION": st.column_config.TextColumn("LOCATION", width="medium"),
        "HIRING_MANAGER": st.column_config.TextColumn("HIRING MANAGER", width="medium"),
        "TIME_POSTED": st.column_config.TextColumn("TIME_POSTED", width="small"),
        "AI SCORE": st.column_config.TextColumn("AI SCORE", width="small"),
        "AI_STATUS": st.column_config.TextColumn("AI STATUS", width="small"),

        "LINK": st.column_config.LinkColumn("LINK", width="medium"),

        # =========================
        # CANONICAL PIPELINE STATE
        # =========================
        "PIPELINE_STAGE": st.column_config.SelectboxColumn(
            "PIPELINE_STAGE",
            options=[
                "New",
                "Saved",
                "Applied",
                "HR Screen",
                "Interview",
                "Final Round",
                "Offer",
                "Rejected",
                "Ghosted"
            ],
            width="medium"
        ),

        "NOTES": st.column_config.TextColumn(
            "NOTES",
            width="large"
        ),

    },
    disabled=[
        "Sr. No",
        "TITLE",
        "COMPANY",
        "LOCATION",
        "TIME_POSTED",
        "AI SCORE",
        "LINK",
    ],
)


def _job_editor_return_differs_input(before_df, after_df):
    cols = ["PIPELINE_STAGE", "NOTES"]
    for c in cols:
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


_job_editor_dirty = _job_editor_return_differs_input(editor_df, edited_df)

# =========================
# BUILD CANONICAL UI STATE
# =========================

updated_states = []

for _, row in edited_df.iterrows():

    pipeline_stage = str(
        row["PIPELINE_STAGE"]
    ).strip()

    applied_state = pipeline_stage in [
        "Applied",
        "HR Screen",
        "Interview",
        "Final Round",
        "Offer",
    ]

    interview_state = pipeline_stage in [
        "Interview",
        "Final Round",
        "Offer",
    ]

    offer_state = pipeline_stage == "Offer"

    rejected_state = pipeline_stage == "Rejected"

    _state = {
        "JOB_KEY": str(row["JOB_KEY"]).strip(),
        "pipeline_stage": pipeline_stage,
        "applied": applied_state,
        "rejected": rejected_state,
        "interview": interview_state,
        "offer": offer_state,
        "notes": str(row["NOTES"]),
    }
    if "JOB_KEY_V2" in row.index:
        _state["JOB_KEY_V2"] = str(row["JOB_KEY_V2"]).strip()
    updated_states.append(_state)

updated_df = pd.DataFrame(updated_states)

# =========================
# PERSIST UI STATE TO HISTORY
# =========================

if dashboard_write_enabled():
    _job_rows_persisted = persist_dashboard_job_edits(updated_df)
    if _job_rows_persisted:
        st.sidebar.caption(
            f"SQLite job state saved ({_job_rows_persisted} rows, SQLITE_DASHBOARD_WRITE=1)"
        )
else:
    historical_df = pd.read_csv(
        str(paths.historical_jobs_csv())
    )

    historical_df["JOB_KEY"] = (
        historical_df["JOB_KEY"]
        .astype(str)
        .str.strip()
    )

    updated_df["JOB_KEY"] = (
        updated_df["JOB_KEY"]
        .astype(str)
        .str.strip()
    )

    # Ensure columns exist + normalize dtypes
    required_cols = {
        "pipeline_stage": "New",
        "applied": False,
        "rejected": False,
        "interview": False,
        "offer": False,
        "notes": "",
    }

    string_cols = [
        "pipeline_stage",
        "notes",
    ]

    bool_cols = [
        "applied",
        "rejected",
        "interview",
        "offer"
    ]

    for col, default_value in required_cols.items():

        if col not in historical_df.columns:
            historical_df[col] = default_value

    # Force string columns
    for col in string_cols:

        historical_df[col] = (
            historical_df[col]
            .fillna("")
            .astype(str)
        )

    # Force boolean columns
    for col in bool_cols:

        historical_df[col] = (
            historical_df[col]
            .fillna(False)
            .astype(bool)
        )

    # Direct row update (V2-first merge key must match listing/editor identity)
    historical_df = _ensure_merge_key_columns(historical_df)
    updated_df = _ensure_merge_key_columns(updated_df)

    historical_df = historical_df.set_index("__merge_key")
    update_index = updated_df.set_index("__merge_key")

    matched_keys = update_index.index.intersection(historical_df.index)

    for col in required_cols.keys():
        historical_df.loc[matched_keys, col] = update_index.loc[matched_keys, col]

    historical_df = historical_df.reset_index()

    historical_df = historical_df.drop(
        columns=["response_status"],
        errors="ignore"
    )

    historical_df.to_csv(
        str(paths.historical_jobs_csv()),
        index=False
    )

# =========================
# 🤝 RECRUITER CRM ANALYTICS
# =========================

st.markdown("---")
st.subheader("🤝 Recruiter CRM")

crm_col1, crm_col2, crm_col3 = st.columns(3)

crm_col1.metric(
    "Total Recruiters",
    len(recruiter_crm_df)
)

crm_col2.metric(
    "Active Recruiters",
    int(
        recruiter_crm_df[
            recruiter_crm_df["currently_active"] == True
        ].shape[0]
    )
)

crm_col3.metric(
    "Recruiters Replied",
    int(
        recruiter_crm_df[
            recruiter_crm_df["recruiter_replied"] == True
        ].shape[0]
    )
)

# =========================
# 🤝 RECRUITER CRM TABLE
# =========================

st.markdown("---")
st.subheader("🤝 Recruiter Relationship Manager")

display_crm_df = recruiter_crm_df.copy()

_tc_vals = pd.to_numeric(
    display_crm_df["touchpoint_count"],
    errors="coerce"
).fillna(0)

display_crm_df["recruiter_responsiveness_score"] = (
    display_crm_df["recruiter_replied"].astype(bool).astype(int) * 40
    + display_crm_df["outreach_sent"].astype(bool).astype(int) * 20
    + (_tc_vals * 5).clip(upper=40)
).clip(upper=100).round(1)

display_crm_df.insert(0, "Sr. No", range(1, len(display_crm_df) + 1))

crm_editor_df = display_crm_df[
    [
        "Sr. No",
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
        "first_seen": "first_seen",
        "last_seen": "last_seen",
        "jobs_connected": "Jobs Connected",
        "recruiter_stage": "Recruiter Status",
    }
)

edited_crm_df = st.data_editor(
    crm_editor_df,
    key="recruiter_crm_editor",
    width="stretch",
    height=400,
    hide_index=True,
    column_order=[
        "Sr. No",
        "Recruiter",
        "Company",
        "Source",
        "first_seen",
        "last_seen",
        "Jobs Connected",
        "Recruiter Status",
    ],
    column_config={
        "RECRUITER_KEY": None,
        "Sr. No": st.column_config.NumberColumn("Sr. No", width="small", disabled=True),
        "Recruiter": st.column_config.TextColumn("Recruiter", disabled=True),
        "Company": st.column_config.TextColumn("Company", disabled=True),
        "Source": st.column_config.TextColumn("Source", disabled=True),
        "first_seen": st.column_config.TextColumn("first_seen", disabled=True),
        "last_seen": st.column_config.TextColumn("last_seen", disabled=True),
        "Jobs Connected": st.column_config.NumberColumn("Jobs Connected", disabled=True),
        "Recruiter Status": st.column_config.SelectboxColumn(
            "Recruiter Status",
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

# =========================
# 💾 SAVE CRM EDITS
# =========================

if dashboard_write_enabled():
    persist_dashboard_crm_edits(
        edited_crm_df["RECRUITER_KEY"].astype(str).tolist(),
        edited_crm_df["Recruiter Status"].astype(str).tolist(),
    )
else:
    crm_save_df = recruiter_crm_df.copy()
    crm_save_df["recruiter_stage"] = edited_crm_df["Recruiter Status"].values

    crm_save_df.to_csv(
        str(paths.recruiter_crm_csv()),
        index=False
    )

if _job_editor_dirty:
    st.rerun()