import pandas as pd
from datetime import datetime, timedelta
import os

import paths

# Empty historical_jobs.csv schema (update_historical_jobs + reset/bootstrap tooling).
HISTORICAL_JOBS_SCHEMA_COLUMNS = [
    "JOB_KEY",
    "JOB_KEY_V2",
    "title",
    "company",
    "location",
    "source",
    "link",
    "ai_score",
    "ai_status",
    "reason",
    "hiring_manager",
    "first_seen",
    "last_seen",
    "times_seen",
    "currently_active",
    "applied",
    "rejected",
    "interview",
    "offer",
    "notes",
    "posted_at_date",
    "age_days",
]


def historical_jobs_schema_columns() -> list[str]:
    """Column order for empty historical_jobs.csv (persistence writer contract)."""
    return list(HISTORICAL_JOBS_SCHEMA_COLUMNS)


# =========================================================
# 🧠 GENERATE STABLE JOB KEY
# =========================================================
def generate_job_key(job):
    """
    Creates stable canonical identifier.

    IMPORTANT:
    - Uses normalized fields
    - Avoids link instability
    - Compatible with future DB migration
    """

    normalized_title = str(
        job.get("normalized_title", "")
    ).strip().lower()

    normalized_company = str(
        job.get("normalized_company", "")
    ).strip().lower()

    return f"{normalized_title}::{normalized_company}"


def _job_key_v2_from_job(job: dict) -> str:
    """Read JOB_KEY_V2 from job dict; empty if absent."""
    v = job.get("JOB_KEY_V2")
    if v is None:
        return ""
    return str(v).strip()


def _resolve_v2_for_persist(job: dict) -> str:
    """V2 key for historical upsert: field on job, else compute via identity module."""
    return _resolve_v2_lookup_key(job)


def _load_historical_index_from_csv() -> dict:
    """
    Build dual maps from historical_jobs.csv (legacy read path).
    """
    HISTORICAL_FILE = paths.historical_jobs_csv()
    empty = {"by_v2": {}, "by_legacy": {}}

    if not HISTORICAL_FILE.is_file():
        return empty

    try:
        historical_df = pd.read_csv(str(HISTORICAL_FILE))
    except Exception:
        return empty

    if "JOB_KEY" not in historical_df.columns:
        return empty

    historical_df["JOB_KEY"] = (
        historical_df["JOB_KEY"]
        .astype(str)
        .str.strip()
    )

    if "JOB_KEY_V2" not in historical_df.columns:
        historical_df["JOB_KEY_V2"] = ""
    else:
        historical_df["JOB_KEY_V2"] = (
            historical_df["JOB_KEY_V2"].fillna("").astype(str).str.strip()
        )

    by_legacy = {}
    by_v2 = {}
    for _, row in historical_df.iterrows():
        row_dict = row.to_dict()
        leg = str(row_dict.get("JOB_KEY", "")).strip()
        if leg:
            by_legacy[leg] = row_dict
        v2 = str(row_dict.get("JOB_KEY_V2", "")).strip()
        if v2:
            by_v2[v2] = row_dict

    return {"by_v2": by_v2, "by_legacy": by_legacy}


def load_historical_index():
    """
    Build dual maps for Phase 2 historical lookup (read paths only).

    When SQLITE_PIPELINE_READ=1, reads from historical_jobs_view; CSV fallback on error.

    Returns:
        {"by_v2": dict[str, dict], "by_legacy": dict[str, dict]}
    """
    from db.read.historical_index import load_historical_index_with_fallback

    index, source = load_historical_index_with_fallback(_load_historical_index_from_csv)
    load_historical_index._last_source = source  # type: ignore[attr-defined]
    if source == "sqlite":
        print("  Pipeline historical index: SQLite (SQLITE_PIPELINE_READ=1)")
    return index


def _resolve_v2_lookup_key(job: dict, trace: dict | None = None) -> str:
    """V2 key for historical lookup: prefer field on job, else compute (lazy import)."""
    v = _job_key_v2_from_job(job)
    if v:
        return v
    if trace is not None:
        trace["historical_lookup_v2_resolve_attempted"] = (
            trace.get("historical_lookup_v2_resolve_attempted", 0) + 1
        )
    try:
        from agent.job_identity import generate_job_key_v2

        v2, _ = generate_job_key_v2(job)
        return str(v2).strip() if v2 else ""
    except Exception:
        if trace is not None:
            trace["historical_lookup_v2_resolve_exception"] = (
                trace.get("historical_lookup_v2_resolve_exception", 0) + 1
            )
        return ""


def lookup_historical_row(historical_index, job: dict, historical_lookup_trace: dict | None = None):
    """
    Phase 2: try JOB_KEY_V2 index first, then legacy JOB_KEY.

    Returns the historical row dict or None. Never raises for missing keys.

    historical_lookup_trace: optional dict for Phase 5 counters only (no routing impact).
    """
    def _bump(key: str, n: int = 1) -> None:
        if historical_lookup_trace is not None:
            historical_lookup_trace[key] = historical_lookup_trace.get(key, 0) + n

    if not historical_index:
        _bump("historical_lookup_empty_index")
        return None

    by_legacy = historical_index.get("by_legacy")
    by_v2 = historical_index.get("by_v2")
    if not isinstance(by_legacy, dict) or not isinstance(by_v2, dict):
        legacy_key = str(job.get("JOB_KEY", "")).strip() or generate_job_key(job)
        row = historical_index.get(legacy_key)
        _bump("historical_lookup_flat_index_path")
        if row is not None:
            _bump("historical_lookup_flat_index_hit")
        else:
            _bump("historical_lookup_flat_index_miss")
        return row if row is not None else None

    _bump("historical_lookup_calls")
    legacy_key = str(job.get("JOB_KEY", "")).strip() or generate_job_key(job)

    v2_key = _resolve_v2_lookup_key(job, historical_lookup_trace)
    if not v2_key:
        _bump("historical_lookup_v2_key_blank")

    v2_index_missed = False
    if v2_key:
        row = by_v2.get(v2_key)
        if row is not None:
            _bump("historical_lookup_v2_index_hit")
            return row
        _bump("historical_lookup_v2_index_miss")
        v2_index_missed = True

    row = by_legacy.get(legacy_key)
    if row is not None:
        _bump("historical_lookup_legacy_fallback_hit")
        if historical_lookup_trace is not None and v2_key and v2_index_missed:
            historical_lookup_trace["historical_lookup_v2_miss_legacy_recover_hit"] = (
                historical_lookup_trace.get(
                    "historical_lookup_v2_miss_legacy_recover_hit", 0
                )
                + 1
            )
            samples = historical_lookup_trace.setdefault(
                "_v2_miss_legacy_recover_samples", []
            )
            if len(samples) < 5:
                samples.append(
                    {
                        "title": str(job.get("title", "") or ""),
                        "company": str(job.get("company", "") or ""),
                        "source": str(job.get("source", "") or ""),
                    }
                )
    else:
        _bump("historical_lookup_legacy_fallback_miss")

    return row if row is not None else None


def _historical_v2_upsert_enabled() -> bool:
    """Phase 6.2: V2-assisted upsert when legacy JOB_KEY misses (default on)."""
    v = os.environ.get("HISTORICAL_V2_UPSERT", "1").strip().lower()
    return v not in ("0", "false", "no", "off")


def _has_nonempty_value(value) -> bool:
    text = str(value if value is not None else "").strip().lower()
    return text not in ("", "nan", "none", "<na>")


def _job_ai_status(job: dict) -> str:
    status = str(job.get("ai_status", "") or "").strip().lower()
    if status in ("scored", "pending", "skipped_by_cap"):
        return status

    if (
        _has_nonempty_value(job.get("score"))
        or _has_nonempty_value(job.get("ai_score"))
        or _has_nonempty_value(job.get("reason"))
    ):
        return "scored"

    return "pending"


def _job_ai_score(job: dict, ai_status: str):
    if ai_status != "scored":
        return ""

    raw_score = job.get("score", job.get("ai_score", ""))
    if not _has_nonempty_value(raw_score):
        return ""

    try:
        return float(raw_score)
    except Exception:
        return ""


# =========================================================
# 📦 UPDATE HISTORICAL MEMORY
# =========================================================
def update_historical_jobs(jobs, upsert_trace=None):

    HISTORICAL_FILE = paths.historical_jobs_csv()

    if upsert_trace is None:
        upsert_trace = {}
    upsert_trace.setdefault("historical_upsert_v2_refresh", 0)
    upsert_trace.setdefault("historical_upsert_v2_new_row", 0)
    upsert_trace.setdefault("historical_upsert_v2_missing_key", 0)

    from db.write.engine import write_primary_enabled

    if write_primary_enabled():
        print("\n" + "=" * 60)
        print("🧠 HISTORICAL MEMORY: skipped CSV write (SQLITE_WRITE_PRIMARY=1)")
        print(f"📦 Session cohort jobs: {len(jobs)}")
        print("=" * 60)
        return

    STALE_JOB_DAYS = 14

    # =====================================================
    # ⏰ CURRENT TIMESTAMP
    # =====================================================
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    today_date = datetime.now().strftime("%Y-%m-%d")

    # =====================================================
    # 📄 LOAD EXISTING HISTORY
    # =====================================================
    if HISTORICAL_FILE.is_file():

        historical_df = pd.read_csv(str(HISTORICAL_FILE))

    else:

        historical_df = pd.DataFrame(columns=historical_jobs_schema_columns())

    if "JOB_KEY_V2" not in historical_df.columns:
        historical_df["JOB_KEY_V2"] = ""
    else:
        historical_df["JOB_KEY_V2"] = (
            historical_df["JOB_KEY_V2"].fillna("").astype(str).str.strip()
        )

    if "ai_status" not in historical_df.columns:
        historical_df["ai_status"] = ""
    historical_df["ai_status"] = (
        historical_df["ai_status"].fillna("").astype(str).str.strip().str.lower()
    )
    missing_ai_status = historical_df["ai_status"].isin(["", "nan", "none"])
    if "ai_score" in historical_df.columns:
        historical_score_present = (
            historical_df["ai_score"].fillna("").astype(str).str.strip()
            != ""
        )
    else:
        historical_df["ai_score"] = ""
        historical_score_present = pd.Series(False, index=historical_df.index)
    if "reason" in historical_df.columns:
        historical_reason_present = (
            historical_df["reason"].fillna("").astype(str).str.strip()
            != ""
        )
    else:
        historical_df["reason"] = ""
        historical_reason_present = pd.Series(False, index=historical_df.index)
    historical_df.loc[
        missing_ai_status & (historical_score_present | historical_reason_present),
        "ai_status",
    ] = "scored"
    historical_df.loc[
        missing_ai_status & ~(historical_score_present | historical_reason_present),
        "ai_status",
    ] = "pending"

    for col in ("posted_at_date", "age_days"):
        if col not in historical_df.columns:
            historical_df[col] = None

    def _apply_posted_date_fields(idx, job):
        incoming_posted = job.get("posted_at_date")
        if incoming_posted is not None and str(incoming_posted).strip():
            historical_df.at[idx, "posted_at_date"] = str(incoming_posted).strip()
        incoming_age = job.get("age_days")
        if incoming_age is not None and incoming_age != "":
            try:
                historical_df.at[idx, "age_days"] = int(incoming_age)
            except (TypeError, ValueError):
                pass

    # =====================================================
    # 🧠 TRACK CURRENT RUN (V2-primary)
    # =====================================================
    current_run_v2_keys = set()
    current_run_matched_indices = set()

    def _refresh_existing_row(idx, job, job_key: str):
        historical_df.at[idx, "JOB_KEY"] = job_key
        historical_df.at[idx, "title"] = job.get("title", "")
        historical_df.at[idx, "company"] = job.get("company", "")
        historical_df.at[idx, "location"] = job.get("location", "")
        historical_df.at[idx, "source"] = job.get("source", "")
        historical_df.at[idx, "link"] = job.get("link", "")

        incoming_ai_status = _job_ai_status(job)
        incoming_score = _job_ai_score(job, incoming_ai_status)
        incoming_reason = str(job.get("reason", "")).strip()

        if incoming_ai_status == "scored":
            historical_df.at[idx, "ai_status"] = "scored"
            if incoming_score != "":
                historical_df.at[idx, "ai_score"] = incoming_score
            if incoming_reason:
                historical_df.at[idx, "reason"] = incoming_reason
        else:
            existing_score = historical_df.at[idx, "ai_score"]
            existing_reason = historical_df.at[idx, "reason"]
            has_existing_ai = _has_nonempty_value(existing_score) or _has_nonempty_value(
                existing_reason
            )
            if has_existing_ai:
                historical_df.at[idx, "ai_status"] = "scored"
            else:
                historical_df.at[idx, "ai_status"] = incoming_ai_status

        incoming_hiring_manager = str(job.get("hiring_manager", "")).strip()
        if incoming_hiring_manager and incoming_hiring_manager.lower() not in [
            "not specified",
            "unknown",
            "nan",
        ]:
            historical_df.at[idx, "hiring_manager"] = incoming_hiring_manager

        last_seen_value = str(historical_df.at[idx, "last_seen"])
        last_seen_date = last_seen_value.split(" ")[0]
        if last_seen_date != today_date:
            historical_df.at[idx, "times_seen"] = (
                int(historical_df.at[idx, "times_seen"]) + 1
            )

        historical_df.at[idx, "last_seen"] = now
        historical_df.at[idx, "currently_active"] = True

        _apply_posted_date_fields(idx, job)

        v2_incoming = _resolve_v2_for_persist(job)
        if v2_incoming:
            historical_df.at[idx, "JOB_KEY_V2"] = v2_incoming
            current_run_v2_keys.add(v2_incoming)

        current_run_matched_indices.add(idx)

    # =====================================================
    # 🔄 PROCESS CURRENT JOBS (V2-primary upsert)
    # =====================================================
    for job in jobs:

        job_key = generate_job_key(job)
        v2_incoming = _resolve_v2_for_persist(job)

        if not v2_incoming:
            upsert_trace["historical_upsert_v2_missing_key"] += 1

        idx = None
        if v2_incoming:
            current_run_v2_keys.add(v2_incoming)
            v2_match = historical_df[historical_df["JOB_KEY_V2"] == v2_incoming]
            if not v2_match.empty:
                idx = v2_match.index[0]

        # =================================================
        # 🆕 NEW JOB (no matching JOB_KEY_V2 row)
        # =================================================
        if idx is None:
            incoming_ai_status = _job_ai_status(job)
            incoming_ai_score = _job_ai_score(job, incoming_ai_status)

            new_row = {
                "JOB_KEY": job_key,
                "JOB_KEY_V2": v2_incoming,
                "title": job.get("title", ""),
                "company": job.get("company", ""),
                "location": job.get("location", ""),
                "source": job.get("source", ""),
                "link": job.get("link", ""),
                "ai_score": incoming_ai_score,
                "ai_status": incoming_ai_status,
                "reason": str(job.get("reason", "")).strip()
                if incoming_ai_status == "scored"
                else "",
                "hiring_manager": job.get("hiring_manager", "Not Specified"),

                "first_seen": now,
                "last_seen": now,
                "times_seen": 1,

                "currently_active": True,

                # user-state fields
                "applied": False,
                "rejected": False,
                "interview": False,
                "offer": False,

                # future intelligence fields
                "notes": "",
                "posted_at_date": job.get("posted_at_date"),
                "age_days": job.get("age_days"),
            }

            historical_df = pd.concat(
                [
                    historical_df,
                    pd.DataFrame([new_row])
                ],
                ignore_index=True
            )
            if v2_incoming:
                upsert_trace["historical_upsert_v2_new_row"] += 1

        # =================================================
        # 🔁 EXISTING JOB (exact JOB_KEY_V2 match)
        # =================================================
        else:

            upsert_trace["historical_upsert_v2_refresh"] += 1
            _refresh_existing_row(idx, job, job_key)

    # ❌ MARK STALE JOBS AS INACTIVE
    for idx, row in historical_df.iterrows():

        row_v2 = str(row.get("JOB_KEY_V2", "") or "").strip()
        if idx in current_run_matched_indices or (
            row_v2 and row_v2 in current_run_v2_keys
        ):

            historical_df.at[idx, "currently_active"] = True
            continue

        try:

            last_seen = datetime.strptime(
                str(row["last_seen"]),
                "%Y-%m-%d %H:%M:%S"
            )

            days_since_seen = (
                datetime.now() - last_seen
            ).days

            # Mark stale jobs inactive
            if days_since_seen >= STALE_JOB_DAYS:

                historical_df.at[
                    idx,
                    "currently_active"
                ] = False

        except:

            # Fallback safety
            historical_df.at[
                idx,
                "currently_active"
            ] = False

    # =====================================================
    # 🧼 CLEANUP (V2-primary; legacy JOB_KEY is not unique)
    # =====================================================
    has_v2 = historical_df["JOB_KEY_V2"].astype(str).str.strip() != ""
    if has_v2.any():
        with_v2 = historical_df[has_v2].drop_duplicates(
            subset=["JOB_KEY_V2"], keep="last"
        )
        without_v2 = historical_df[~has_v2]
        historical_df = pd.concat([with_v2, without_v2], ignore_index=True)

    # =====================================================
    # 📊 SORTING
    # =====================================================
    historical_df = historical_df.sort_values(
        by=["currently_active", "last_seen"],
        ascending=[False, False]
    )

    # =====================================================
    # 💾 SAVE
    # =====================================================
    historical_df = historical_df.drop(
        columns=["response_status"],
        errors="ignore"
    )
    ordered_cols = historical_jobs_schema_columns()
    extra_cols = [c for c in historical_df.columns if c not in ordered_cols]
    historical_df = historical_df.reindex(columns=ordered_cols + extra_cols)
    historical_df.to_csv(str(HISTORICAL_FILE), index=False)

    print("\n" + "=" * 60)
    print("🧠 HISTORICAL MEMORY UPDATED")
    print(f"📦 Total historical jobs: {len(historical_df)}")
    print("=" * 60)