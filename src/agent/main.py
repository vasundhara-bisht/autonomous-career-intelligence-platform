import os
import pandas as pd
from datetime import UTC, datetime

import paths

# =========================
# 📦 IMPORT SCRAPERS
# =========================
from scraper.weworkremotely import scrape_weworkremotely_jobs
from scraper.greenhouse import scrape_greenhouse_jobs
from scraper.lever import scrape_lever_jobs
from scraper.linkedin import scrape_linkedin_jobs
from scraper.linkedin_query_orchestrator import run_linkedin_acquisition_session
from scraper.instahyre import scrape_instahyre_feed
from scraper.instahyre_feed_orchestrator import run_instahyre_feed_session

# =========================
# 📦 IMPORT JOBS
# =========================
from agent.ai_batch_scorer import batch_score_jobs, validate_ai_batch_results
from agent.ai_runtime_config import resolve_batch_size, resolve_debug_limit
from agent.profile_loader import load_candidate_profile
from agent.filter_engine import apply_stage1_filter
from agent.dedup_engine import deduplicate_jobs
from agent.job_description_persistence import (
    load_description_store,
    flush_description_store,
    ensure_description_for_job,
    try_hydrate_from_store,
)
from agent.normalizer import normalize_job
from agent.logger import (
    Stage1Aggregator,
    debug_stage1_enabled,
    log_accepted,
    log_check,
    log_job_start,
    log_rejected,
    log_section,
)
from agent.historical_persistence import (
    update_historical_jobs,
    generate_job_key,
    load_historical_index,
    lookup_historical_row,
)
from agent.job_identity import (
    generate_job_key_v2,
    instrument_jobs_identity_v2,
    log_job_identity_metrics,
    log_production_identity_health_summary,
    log_routing_lookup_summary,
    log_compact_unresolved_summary,
    collect_phase6_continuity_metrics,
    build_unresolved_identity_funnel,
    snapshot_unresolved_segment,
    debug_identity_enabled,
)
from agent.recruiter_crm import update_recruiter_crm
from db.services import (
    csv_ai_status_dist,
    csv_runtime_counts,
    dual_write_runtime_snapshot,
    log_dual_write_summary,
)
from db.bootstrap import ensure_database_ready
from db.config import sqlite_flag
from db.read.engine import get_read_session
from db.read.export_cohort import load_current_jobs_export_source_df

# Canonical jobs.csv export columns (empty export + reset/bootstrap tooling).
JOBS_CSV_SCHEMA_COLUMNS = [
    "id",
    "JOB_KEY",
    "JOB_KEY_V2",
    "identity_source",
    "title",
    "company",
    "location",
    "link",
    "source",
    "time_posted",
    "applied",
    "hiring_manager",
    "ai_score",
    "ai_status",
    "linkedin_query_id",
    "linkedin_query_group",
    "linkedin_query_label",
    "linkedin_filter_profile",
    "linkedin_query_role",
    "linkedin_run_ts",
    "rejected",
    "reason",
    "priority",
]


def jobs_csv_schema_columns(*, union_with_existing_file: bool = True) -> list[str]:
    """
    Column order for empty jobs.csv aligned with save_to_csv export shape.
    Optionally unions columns from an existing jobs.csv on disk.
    """
    import os

    cols = list(JOBS_CSV_SCHEMA_COLUMNS)
    jobs_path = paths.jobs_csv()
    if union_with_existing_file and jobs_path.is_file():
        try:
            header = pd.read_csv(str(jobs_path), nrows=0).columns.tolist()
            for c in header:
                if c not in cols:
                    cols.append(c)
        except Exception:
            pass
    return cols


# =========================
# 💾 SAVE TO CSV (FINAL PIPELINE)
# =========================
_D2_METADATA_WARN_COLUMNS = [
    "linkedin_query_id",
    "linkedin_query_group",
    "linkedin_query_label",
    "linkedin_filter_profile",
    "linkedin_query_role",
    "linkedin_run_ts",
    "instahyre_feed_id",
    "instahyre_query_id",
    "instahyre_query_label",
    "instahyre_run_ts",
]

_D2_HARD_PARITY_COLUMNS = [
    "JOB_KEY_V2",
    "JOB_KEY",
    "identity_source",
    "title",
    "company",
    "location",
    "link",
    "source",
    "time_posted",
    "hiring_manager",
    "ai_score",
    "ai_status",
    "rejected",
    "reason",
    "priority",
]


def _normalize_time_rank(value) -> int:
    if not value:
        return 999
    text = str(value).lower().strip()
    try:
        if text.endswith("d") and text[:-1].isdigit():
            return int(text[:-1]) * 24
        if "just now" in text:
            return 1
        if "hour" in text:
            return int(text.split()[0])
        if "day" in text:
            return int(text.split()[0]) * 24
        if "week" in text:
            return int(text.split()[0]) * 24 * 7
    except Exception:
        return 999
    return 999


def _is_bangalore(loc) -> bool:
    if pd.isna(loc):
        return False
    loc = str(loc).lower()
    return any(x in loc for x in ["bangalore", "karnataka"])


def _prepare_jobs_export_df(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if out.empty:
        return out

    out.columns = out.columns.str.strip()
    if "normalized_title" in out.columns and "normalized_company" in out.columns:
        out["JOB_KEY"] = (
            out["normalized_title"].astype(str).str.strip().str.lower()
            + "::"
            + out["normalized_company"].astype(str).str.strip().str.lower()
        )
    elif "JOB_KEY" not in out.columns:
        out["JOB_KEY"] = ""

    if "JOB_KEY_V2" not in out.columns:
        out["JOB_KEY_V2"] = ""
    out["JOB_KEY_V2"] = out["JOB_KEY_V2"].fillna("").astype(str).str.strip()
    missing_v2 = out["JOB_KEY_V2"] == ""
    if missing_v2.any():
        for idx in out.index[missing_v2]:
            row = out.loc[idx].to_dict()
            v2, src = generate_job_key_v2(row)
            out.at[idx, "JOB_KEY_V2"] = str(v2 or "")
            if "identity_source" not in out.columns:
                out["identity_source"] = ""
            out.at[idx, "identity_source"] = str(src or "")

    out = out.drop(
        columns=[
            "description",
            "normalized_title",
            "normalized_company",
            "posted_at_raw",
            "posted_at_source",
        ],
        errors="ignore",
    )

    if "score" in out.columns:
        if "ai_score" not in out.columns:
            out.rename(columns={"score": "ai_score"}, inplace=True)
        else:
            fallback_score = pd.to_numeric(out["score"], errors="coerce")
            existing_score = pd.to_numeric(out["ai_score"], errors="coerce")
            out["ai_score"] = existing_score.where(existing_score.notna(), fallback_score)

    if "ai_score" not in out.columns:
        out["ai_score"] = pd.NA
    if "reason" not in out.columns:
        out["reason"] = ""
    out["ai_score"] = pd.to_numeric(out["ai_score"], errors="coerce")
    out["reason"] = out["reason"].fillna("").astype(str)

    if "ai_status" not in out.columns:
        has_score = out["ai_score"].notna()
        has_reason = out["reason"].fillna("").astype(str).str.strip() != ""
        out["ai_status"] = (has_score | has_reason).map({True: "scored", False: "pending"})
    else:
        out["ai_status"] = out["ai_status"].fillna("").astype(str).str.strip().str.lower()
        missing_status = out["ai_status"].isin(["", "nan", "none"])
        has_score = out["ai_score"].notna()
        has_reason = out["reason"].fillna("").astype(str).str.strip() != ""
        out.loc[missing_status & (has_score | has_reason), "ai_status"] = "scored"
        out.loc[missing_status & ~(has_score | has_reason), "ai_status"] = "pending"
    out.loc[out["ai_status"] != "scored", "ai_score"] = pd.NA

    out = out[out["title"].notna()]
    out = out[out["link"].notna()]

    out["location"] = out["location"].fillna("Unknown")
    out["location"] = out["location"].apply(
        lambda x: x.replace("Bengaluru", "Bangalore") if isinstance(x, str) else x
    )
    out["priority"] = out["location"].apply(_is_bangalore)

    if "time_posted" not in out.columns:
        out["time_posted"] = "Unknown"
    out["time_rank"] = out["time_posted"].apply(_normalize_time_rank)
    out["_is_scored"] = out["ai_status"].eq("scored")
    out["_sort_ai_score"] = out["ai_score"].fillna(-1)
    out = out.sort_values(
        by=["priority", "_is_scored", "_sort_ai_score", "time_rank"],
        ascending=[False, False, False, True],
    )
    out = out.drop(columns=["time_rank", "_is_scored", "_sort_ai_score"], errors="ignore")

    if "id" not in out.columns:
        out.insert(0, "id", range(1, len(out) + 1))
    return out


def _d2_export_from_db_enabled() -> bool:
    from db.write.engine import export_jobs_csv_enabled

    if not export_jobs_csv_enabled():
        return False
    if not sqlite_flag("SQLITE_ENABLED"):
        return False
    return sqlite_flag("SQLITE_EXPORT_FROM_DB")


def _d2_parity_bool_value(value: object) -> bool:
    """Normalize user-state booleans for D2 hard parity (legacy bool vs DB 0/1)."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return False
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ("", "nan", "none"):
        return False
    if text in ("true", "1", "yes"):
        return True
    if text in ("false", "0", "no"):
        return False
    return bool(value)


def _d2_parity_bool_series(series: pd.Series) -> pd.Series:
    return series.map(_d2_parity_bool_value)


def _d2_hard_parity_check(legacy_df: pd.DataFrame, db_df: pd.DataFrame) -> list[str]:
    errors: list[str] = []
    if len(legacy_df.index) == 0 and len(db_df.index) == 0:
        return errors
    if len(legacy_df.index) != len(db_df.index):
        errors.append(f"row count mismatch legacy={len(legacy_df.index)} db={len(db_df.index)}")
    if "JOB_KEY_V2" not in legacy_df.columns or "JOB_KEY_V2" not in db_df.columns:
        errors.append("missing JOB_KEY_V2 for per-key parity")
        return errors

    l = legacy_df.copy()
    d = db_df.copy()
    l["JOB_KEY_V2"] = l["JOB_KEY_V2"].fillna("").astype(str).str.strip()
    d["JOB_KEY_V2"] = d["JOB_KEY_V2"].fillna("").astype(str).str.strip()
    l = l[l["JOB_KEY_V2"] != ""].drop_duplicates("JOB_KEY_V2")
    d = d[d["JOB_KEY_V2"] != ""].drop_duplicates("JOB_KEY_V2")
    l = l.set_index("JOB_KEY_V2")
    d = d.set_index("JOB_KEY_V2")
    common = l.index.intersection(d.index)
    if len(common) != len(l.index) or len(common) != len(d.index):
        errors.append(
            f"keyset mismatch legacy={len(l.index)} db={len(d.index)} common={len(common)}"
        )

    for col in _D2_HARD_PARITY_COLUMNS:
        if col == "JOB_KEY_V2":
            continue
        if col not in l.columns or col not in d.columns:
            errors.append(f"missing parity column {col}")
            continue
        if col == "ai_score":
            lv = pd.to_numeric(l.loc[common, col], errors="coerce").fillna(-999999)
            dv = pd.to_numeric(d.loc[common, col], errors="coerce").fillna(-999999)
            mismatch = (lv - dv).abs() > 0.001
        elif col == "rejected":
            lv = _d2_parity_bool_series(l.loc[common, col])
            dv = _d2_parity_bool_series(d.loc[common, col])
            mismatch = lv != dv
        else:
            lv = l.loc[common, col].fillna("").astype(str).str.strip()
            dv = d.loc[common, col].fillna("").astype(str).str.strip()
            mismatch = lv != dv
        mismatch_count = int(mismatch.sum())
        if mismatch_count:
            errors.append(f"{col} mismatches: {mismatch_count}")
    return errors


def _d2_metadata_warnings(legacy_df: pd.DataFrame, db_df: pd.DataFrame) -> list[str]:
    warnings: list[str] = []
    for col in _D2_METADATA_WARN_COLUMNS:
        if col not in legacy_df.columns:
            continue
        legacy_filled = int(legacy_df[col].fillna("").astype(str).str.strip().ne("").sum())
        if legacy_filled == 0:
            continue
        db_filled = (
            int(db_df[col].fillna("").astype(str).str.strip().ne("").sum())
            if col in db_df.columns
            else 0
        )
        if db_filled < legacy_filled:
            warnings.append(f"{col} coverage legacy={legacy_filled} db={db_filled}")
    return warnings


def _d2_metadata_hard_parity_enabled() -> bool:
    return sqlite_flag("SQLITE_METADATA_HARD_PARITY")


def _save_to_csv_df(df: pd.DataFrame) -> None:
    if df.empty:
        pd.DataFrame(columns=jobs_csv_schema_columns(union_with_existing_file=False)).to_csv(
            str(paths.jobs_csv()), index=False
        )
        print("\n✅ Session export updated: 0 jobs")
        return
    df.to_csv(str(paths.jobs_csv()), index=False)
    print(f"\n✅ Session export updated: {len(df)} jobs")


def save_to_csv(jobs):
    df = _prepare_jobs_export_df(pd.DataFrame(jobs))
    _save_to_csv_df(df)


def save_to_csv_via_db_export(jobs) -> bool:
    if not _d2_export_from_db_enabled():
        save_to_csv(jobs)
        return False

    legacy_df = _prepare_jobs_export_df(pd.DataFrame(jobs))
    if legacy_df.empty:
        _save_to_csv_df(legacy_df)
        print("  jobs.csv export_mode=legacy_empty_cohort")
        return False
    try:
        ensure_database_ready()
        with get_read_session() as session:
            db_source = load_current_jobs_export_source_df(session)
        db_df = _prepare_jobs_export_df(db_source)
        hard_errors = _d2_hard_parity_check(legacy_df, db_df)
        if hard_errors:
            print("\n⚠️ D2 DB export hard parity failed; falling back to legacy save_to_csv")
            for item in hard_errors:
                print(f"  - {item}")
            save_to_csv(jobs)
            return False
        metadata_warnings = _d2_metadata_warnings(legacy_df, db_df)
        if _d2_metadata_hard_parity_enabled() and metadata_warnings:
            print("\n⚠️ D2 DB export hard parity failed; falling back to legacy save_to_csv")
            for item in metadata_warnings:
                print(f"  - {item}")
            save_to_csv(jobs)
            return False
        for item in metadata_warnings:
            print(f"  WARN metadata parity: {item}")
        _save_to_csv_df(db_df)
        print("  jobs.csv export_mode=db_current_jobs_view")
        return True
    except Exception as exc:
        print(f"\n⚠️ D2 DB export failed ({exc}); falling back to legacy save_to_csv")
        save_to_csv(jobs)
        return False


def _is_valid_job_key(job_key: str) -> bool:
    if not isinstance(job_key, str):
        return False

    job_key = job_key.strip().lower()
    if not job_key or "::" not in job_key:
        return False

    parts = job_key.split("::", 1)
    if len(parts) != 2:
        return False

    left = parts[0].strip()
    right = parts[1].strip()

    if not left or not right:
        return False

    if left in ["unknown", "nan"] or right in ["unknown", "nan"]:
        return False

    return True


def _passes_known_job_hygiene(job: dict) -> bool:
    title = str(job.get("title", "")).strip()
    company = str(job.get("company", "")).strip()
    job_key = str(job.get("JOB_KEY", "")).strip()

    if not title or title.lower() in ["unknown", "nan"]:
        return False

    if not company or company.lower() in ["unknown", "nan"]:
        return False

    if not _is_valid_job_key(job_key):
        return False

    return True


def _historical_job_needs_ai_fallback(h_row: dict) -> bool:
    ai_status = str(h_row.get("ai_status", "") or "").strip().lower()
    reason = str(h_row.get("reason", "")).strip()

    if ai_status == "scored":
        return not reason

    try:
        ai_score = float(h_row.get("ai_score", 0))
    except Exception:
        ai_score = 0

    return ai_score <= 0 or not reason


def materialize_fully_processed_job(job: dict, historical_row: dict) -> None:
    """
    Merge historical memory into the scrape dict for export/final merge.
    Scrape fields (title, company, link, recruiters, etc.) stay authoritative.
    """
    raw_ai_score = historical_row.get("ai_score", "")
    has_ai_score = str(raw_ai_score).strip().lower() not in ("", "nan", "none")
    try:
        ai_score = float(raw_ai_score)
    except (TypeError, ValueError):
        ai_score = None
    if has_ai_score and ai_score is not None:
        job["score"] = ai_score

    reason = str(historical_row.get("reason", "") or "").strip()
    if reason:
        job["reason"] = reason

    ai_status = str(historical_row.get("ai_status", "") or "").strip().lower()
    job["ai_status"] = ai_status if ai_status else "scored"

    for field in ("applied", "rejected"):
        if field not in historical_row:
            continue
        raw = historical_row[field]
        if raw is None:
            continue
        text = str(raw).strip().lower()
        if text in ("", "nan", "none"):
            continue
        if text in ("true", "1", "yes"):
            job[field] = True
        elif text in ("false", "0", "no"):
            job[field] = False
        elif isinstance(raw, bool):
            job[field] = raw


def _production_final_merge_key(job: dict) -> str:
    """
    Phase 7B: V2-only final merge key (compute V2 if missing on job dict).
    Legacy JOB_KEY is not used for merge routing.
    """
    try:
        v2 = str(job.get("JOB_KEY_V2", "") or "").strip()
        if v2:
            return v2
        v2, _ = generate_job_key_v2(job)
        v2 = str(v2 or "").strip()
        if v2:
            return v2
        return f"__production_merge_{id(job)}"
    except Exception:
        return f"__production_merge_{id(job)}"


# =========================
# 🚀 MAIN EXECUTION
# =========================
if __name__ == "__main__":
    import os

    from scraper.acquisition_gate import format_skip_message, resolve_max_runs

    migrated = paths.migrate_legacy_root_runtime_files()
    if migrated:
        print(f"📁 Migrated runtime files to {paths.DATA_DIR}: {', '.join(migrated)}")

    print("🚀 Starting job aggregation...\n")
    pipeline_started_at = datetime.now(UTC).replace(tzinfo=None)

    # =========================
    # 🌍 WeWorkRemotely
    # =========================
    _wwr_gate = resolve_max_runs(
        "WEWORKREMOTELY_MAX_RUNS",
        config_default=1,
        source_label="WeWorkRemotely",
    )
    jobs_wwr = []
    if _wwr_gate.disabled:
        print(format_skip_message(_wwr_gate, "WeWorkRemotely"))
    else:
        try:
            jobs_wwr = scrape_weworkremotely_jobs()
        except Exception as e:
            print(f"WeWorkRemotely failed: {e}")
            jobs_wwr = []

    # =========================
    # 🏢 Greenhouse
    # =========================
    _gh_gate = resolve_max_runs(
        "GREENHOUSE_MAX_RUNS",
        config_default=1,
        source_label="Greenhouse",
    )
    jobs_greenhouse = []
    if _gh_gate.disabled:
        print(format_skip_message(_gh_gate, "Greenhouse"))
    else:
        try:
            jobs_greenhouse = scrape_greenhouse_jobs()
        except Exception as e:
            print(f"Greenhouse failed: {e}")
            jobs_greenhouse = []

    # =========================
    # ⚙️ Lever
    # =========================
    _lever_gate = resolve_max_runs(
        "LEVER_MAX_RUNS",
        config_default=1,
        source_label="Lever",
    )
    jobs_lever = []
    if _lever_gate.disabled:
        print(format_skip_message(_lever_gate, "Lever"))
    else:
        try:
            jobs_lever = scrape_lever_jobs()
        except Exception as e:
            print(f"Lever failed: {e}")
            jobs_lever = []

    # =========================
    # 🔥 LINKEDIN (MULTI-STRATEGY ORCHESTRATION)
    # =========================
    # Config: config/linkedin_queries.json
    # Env: LINKEDIN_MAX_RUNS, LINKEDIN_QUERY_IDS, LINKEDIN_LEGACY_SINGLE_QUERY=1
    _linkedin_gate = resolve_max_runs(
        "LINKEDIN_MAX_RUNS",
        config_default=5,
        source_label="LinkedIn",
    )
    jobs_linkedin = []
    if _linkedin_gate.disabled:
        print(format_skip_message(_linkedin_gate, "LinkedIn"))
    elif os.environ.get("LINKEDIN_LEGACY_SINGLE_QUERY", "").strip().lower() in (
        "1",
        "true",
        "yes",
    ):
        linkedin_searches = [
            (
                "Core PM India",
                "https://www.linkedin.com/jobs/search/?keywords=product%20manager&location=India",
            ),
        ]
        for label, url in linkedin_searches:
            try:
                jobs = scrape_linkedin_jobs(url)
                print(f"LinkedIn [{label}]: {len(jobs)} jobs")
                jobs_linkedin += jobs
            except Exception as e:
                print(f"LinkedIn failed [{label}]: {e}")
    else:
        jobs_linkedin = run_linkedin_acquisition_session(
            scrape_linkedin_jobs,
            max_runs=_linkedin_gate.effective_max_runs,
        )

    print(f"\n📦 LINKEDIN RAW JOBS COLLECTED: {len(jobs_linkedin)}")

    # =========================
    # 🟣 INSTAHYRE (feed orchestration — INSTAHYRE_MAX_RUNS=0 to skip)
    # =========================
    _instahyre_gate = resolve_max_runs(
        "INSTAHYRE_MAX_RUNS",
        config_default=2,
        source_label="Instahyre",
    )
    jobs_instahyre: list = []
    if _instahyre_gate.disabled:
        print(format_skip_message(_instahyre_gate, "Instahyre"))
    else:
        print("\n🟣 INSTAHYRE ACQUISITION STARTED")
        try:
            instahyre_session = run_instahyre_feed_session(
                scrape_instahyre_feed,
                max_feeds=_instahyre_gate.effective_max_runs,
            )
            jobs_instahyre = instahyre_session.jobs
        except Exception as e:
            import traceback

            print(f"❌ Instahyre acquisition failed: {e}")
            traceback.print_exc()
            jobs_instahyre = []

    # =========================
    # 🔗 COMBINE ALL SOURCES
    # =========================
    all_jobs = (
        jobs_linkedin
        + jobs_greenhouse
        + jobs_wwr
        + jobs_lever
        + jobs_instahyre
    )

    raw_jobs_count = len(all_jobs)

    # =========================================================
    # ⚪ STAGE 0 — NORMALIZATION
    # =========================================================
    # Purpose:
    # - Standardize scraper outputs
    # - Clean inconsistent formatting
    # - Stabilize downstream pipeline
    #
    # Runs BEFORE:
    # - filtering
    # - deduplication
    # - description fetching
    # - AI scoring
    # =========================================================

    norm_banner = "=" * 60
    print(f"\n{norm_banner}")
    print("🧼 NORMALIZING JOB DATA...")

    all_jobs = [normalize_job(job) for job in all_jobs]

    print("✅ Normalization Completed")
    print(f"{norm_banner}\n")

    # Phase 6.1: V2 instrumentation before historical lookup (in-memory; export unchanged)
    identity_metrics = instrument_jobs_identity_v2(all_jobs)
    scraped_jobs_intake = all_jobs

    # =========================================================
    # 🧠 INCREMENTAL SPLIT (HISTORICAL LOOKUP)
    # =========================================================
    historical_index = load_historical_index()

    historical_lookup_trace: dict = {}

    fully_processed_jobs = []
    needs_ai_only_jobs = []
    brand_new_jobs = []

    for job in all_jobs:
        job_key = generate_job_key(job)
        job["JOB_KEY"] = job_key

        historical_row = lookup_historical_row(
            historical_index, job, historical_lookup_trace
        )

        if not historical_row:
            brand_new_jobs.append(job)
            continue

        # Lightweight passthrough hygiene: prevent historical garbage propagation
        if not _passes_known_job_hygiene(job):
            brand_new_jobs.append(job)
            continue

        if _historical_job_needs_ai_fallback(historical_row):
            needs_ai_only_jobs.append(job)
        else:
            materialize_fully_processed_job(job, historical_row)
            fully_processed_jobs.append(job)

    split_fully_processed = len(fully_processed_jobs)
    split_needs_ai_only = len(needs_ai_only_jobs)
    split_brand_new = len(brand_new_jobs)

    print("\n--- Identity routing (historical lookup) ---")
    print(
        f"  Fully processed (historical AI materialized; skip Stage 1 / descriptions / AI): "
        f"{split_fully_processed}"
    )
    print(f"  Needs AI only (hydrate + AI queue): {split_needs_ai_only}")
    print(f"  Brand new (full pipeline path): {split_brand_new}")
    print("  Canonical key: JOB_KEY_V2 (legacy JOB_KEY fallback during migration)")

    log_routing_lookup_summary(historical_lookup_trace)
    log_compact_unresolved_summary(
        "Intake (raw scraped jobs)",
        snapshot_unresolved_segment(scraped_jobs_intake),
    )
    print()

    # brand_new → Stage 1 → dedup → descriptions → AI
    # needs_ai_only → join AI queue only (historical row already passed prior pipeline)
    all_jobs = brand_new_jobs

    unresolved_segments: dict = {
        "unresolved_pre_stage1": list(brand_new_jobs),
    }

    # =========================================================
    # 🔵 STAGE A — CENTRALIZED STAGE 1 FILTER
    # =========================================================
    # Purpose:
    # - Apply unified scoring logic
    # - Reject irrelevant roles
    # - Keep only promising PM jobs
    #
    # IMPORTANT:
    # - Scrapers already apply lightweight pre-filters
    # - This is the FINAL centralized filter
    #
    # Output:
    # - Relevant jobs only
    # =========================================================

    print("\n🚦 Starting Stage 1 Filtering...\n")
    final_jobs = []
    stage1_stats = Stage1Aggregator()
    stage1_debug = debug_stage1_enabled()

    for job in all_jobs:
        if stage1_debug:
            log_job_start(job)

        # =========================
        # 🎯 FILTER
        # =========================
        result = apply_stage1_filter(job)

        score = result.get("score", 0) if result else 0
        accepted = bool(result) and not result.get("rejected") and score != 0

        if stage1_debug:
            log_check(score)
            if accepted:
                log_accepted()
            else:
                log_rejected(score)

        stage1_stats.record(job, score, accepted=accepted)

        if not accepted:
            continue

        final_jobs.append(result)

    stage1_stats.print_summary()
    log_section(f"🎯 AFTER STAGE 1 FILTER: {len(final_jobs)} jobs")

    after_stage1_count = len(final_jobs)

    all_jobs = final_jobs
    unresolved_segments["unresolved_post_stage1"] = list(final_jobs)

    # =========================================================
    # 🟣 STAGE B — DEDUPLICATION
    # =========================================================
    # Purpose:
    # - Remove duplicate jobs across all sources
    # - Prevent repeated AI scoring
    # - Prevent repeated description fetching
    #
    # Logic:
    # - Exact link matching
    # - Fuzzy title/company matching
    #
    # IMPORTANT:
    # - Runs AFTER centralized filtering
    # - Runs BEFORE description fetching
    #
    # Output:
    # - Unique relevant jobs only
    # =========================================================
    
    log_section("🧹 RUNNING DEDUPLICATION")

    dedup_observability: dict = {}
    all_jobs = deduplicate_jobs(all_jobs, observability=dedup_observability)

    print(f"✅ AFTER DEDUPLICATION: {len(all_jobs)} jobs\n")
    dedup_jobs_count = len(all_jobs)
    unresolved_segments["unresolved_survived_dedup"] = list(all_jobs)

    # =========================
    # 📊 SOURCE BREAKDOWN (deduped list, before descriptions)
    # =========================
    log_section("📊 SOURCE BREAKDOWN")
    source_by_name = {}
    for job in all_jobs:
        source = job.get("source", "unknown")
        source_by_name[source] = source_by_name.get(source, 0) + 1

    for source, count in sorted(source_by_name.items()):
        print(f"{source}: {count}")

    # =========================================================
    # 🟡 STAGE C — DESCRIPTION ENRICHMENT
    # =========================================================
    # Purpose:
    # - Fetch detailed job descriptions
    # - Only for unique + relevant jobs
    #
    # Why here?
    # - Avoid expensive browser calls on duplicates
    # - Major performance optimization
    #
    # Output:
    # - Description-enriched jobs
    # =========================================================

    log_section("📄 FETCHING JOB DESCRIPTIONS")

    desc_jobs_total = len(all_jobs)
    print(f"📄 Brand-new jobs entering description pass: {desc_jobs_total}")

    desc_store = load_description_store()
    desc_stats: dict = {
        "reused": 0,
        "fetched": 0,
        "persisted": 0,
        "reused_brand_new": 0,
        "reused_needs_ai_only": 0,
        "reused_via_v2": 0,
        "reused_via_legacy": 0,
        "scrape_description_usable": 0,
        "fetch_attempted": 0,
        "fetch_improved": 0,
        "persisted_from_scrape": 0,
        "persisted_from_fetch": 0,
        "fetch_would_have_overwritten_valid_description": 0,
    }

    enriched_jobs = []

    for job in all_jobs:
        ensure_description_for_job(job, desc_store, desc_stats, bucket="brand_new")
        enriched_jobs.append(job)

    flush_description_store(desc_store)

    for job in needs_ai_only_jobs:
        try_hydrate_from_store(job, desc_store, desc_stats, bucket="needs_ai_only")

    print(f"✅ Description enrichment pass complete: {len(enriched_jobs)} brand-new jobs")
    print("\n--- Brand-new description pass ---")
    print(f"  Jobs in pass: {desc_jobs_total}")
    print(f"  Cache reused: {desc_stats.get('reused_brand_new', 0)}")
    fetched_n = int(desc_stats.get("fetched", 0))
    persisted_n = int(desc_stats.get("persisted", 0))
    print(f"  HTTP fetched: {fetched_n}")
    print(f"  Persisted to store: {persisted_n}")
    print(f"  Scrape description usable: {desc_stats.get('scrape_description_usable', 0)}")
    print(f"  Fetch attempted: {desc_stats.get('fetch_attempted', 0)}")
    print(f"  Fetch improved: {desc_stats.get('fetch_improved', 0)}")
    print(f"  Persisted from scrape: {desc_stats.get('persisted_from_scrape', 0)}")
    print(f"  Persisted from fetch: {desc_stats.get('persisted_from_fetch', 0)}")
    overwritten = desc_stats.get("fetch_would_have_overwritten_valid_description", 0)
    print(f"  Fetch would have overwritten valid description: {overwritten}")
    if fetched_n != persisted_n:
        print(
            f"  Note: {fetched_n - persisted_n} fetch(es) not persisted "
            f"(empty or non-persistable description)"
        )
    needs_ai_hydrated = desc_stats.get("reused_needs_ai_only", 0)
    needs_ai_miss = max(0, split_needs_ai_only - needs_ai_hydrated)
    print("\n--- Needs-AI-only cache hydration (no HTTP fetch) ---")
    print(f"  Jobs in queue: {split_needs_ai_only}")
    print(f"  Hydrated from cache: {needs_ai_hydrated}")
    print(f"  Cache miss (no hydrate): {needs_ai_miss}")
    if needs_ai_miss > 0:
        print(
            "  Note: cache misses still enter AI queue "
            "(may run without cached description)"
        )
    print(
        f"  Lookup: V2 {desc_stats.get('reused_via_v2', 0)} | "
        f"legacy {desc_stats.get('reused_via_legacy', 0)}"
    )
    if debug_identity_enabled():
        print(f"  📚 Reused (total, DEBUG_IDENTITY): {desc_stats.get('reused', 0)}")


    all_jobs = enriched_jobs
    description_jobs_count = len(all_jobs)

    # =========================
    # 🔽 AI queue: brand_new (post-description) + needs_ai_only (direct)
    # =========================
    combined_ai_queue = all_jobs + needs_ai_only_jobs

    combined_ai_queue = sorted(
        combined_ai_queue,
        key=lambda x: x.get("time_rank", 999)
    )
    unresolved_segments["unresolved_ai_candidates"] = list(combined_ai_queue)

    # =========================
    # 🧪 AI scoring cap (persistence-safe)
    # =========================
    DEBUG_LIMIT = resolve_debug_limit()
    ai_candidates_before_limit = len(combined_ai_queue)
    ai_capped_count = min(ai_candidates_before_limit, DEBUG_LIMIT)
    ai_skipped_by_cap = max(0, ai_candidates_before_limit - DEBUG_LIMIT)

    persistent_jobs = list(combined_ai_queue)
    ai_scoring_jobs = persistent_jobs[:DEBUG_LIMIT]
    pending_ai_jobs = persistent_jobs[DEBUG_LIMIT:]

    for job in persistent_jobs:
        job.pop("score", None)
        job.pop("ai_score", None)
        job["reason"] = ""
        job["ai_status"] = "pending"

    for job in pending_ai_jobs:
        job["ai_status"] = "skipped_by_cap"

    print(
        f"🧠 needs_ai_only jobs routed directly to AI: {split_needs_ai_only}"
    )
    print("\n--- AI scoring cap (DEBUG_LIMIT) ---")
    print(f"  Total AI candidates: {ai_candidates_before_limit}")
    print(f"  Capped for scoring: {ai_capped_count}")
    print(f"  Pending/skipped by cap: {ai_skipped_by_cap}")
    print(f"  Historical persistence cohort: {len(persistent_jobs)}")
    if ai_skipped_by_cap > 0:
        print(
            "  Note: Jobs skipped by cap are persisted with blank AI score for later scoring"
        )

    # =========================================================
    # 🔴 STAGE D — AI EVALUATION
    # =========================================================
    # Purpose:
    # - Deep semantic job evaluation
    # - Resume/profile alignment
    # - Priority scoring
    #
    # AI evaluates:
    # - Responsibilities
    # - Domain
    # - Seniority
    # - Product ownership
    #
    # Runs ONLY on:
    # - brand_new: filtered, deduplicated, description-enriched
    # - needs_ai_only: joined at AI queue (no re-run of Stage 1 / dedup / descriptions)
    #
    # Output:
    # - ai_score
    # - reasoning
    # =========================================================

    BATCH_SIZE = resolve_batch_size()
    ai_results_applied = 0
    ai_candidate_count = len(ai_scoring_jobs)

    if ai_candidate_count > 0:
        import time

        total_batches = (ai_candidate_count + BATCH_SIZE - 1) // BATCH_SIZE
        ai_banner = "=" * 60
        print(f"\n{ai_banner}")
        print("🤖 STARTING AI BATCH SCORING")
        print(f"{ai_banner}\n")
        print(f"📦 Total AI Candidate Jobs: {ai_candidate_count}")
        print(f"🧠 Total AI Scoring Batches: {total_batches}")
        print(f"📏 Batch Size: {BATCH_SIZE}\n")

        candidate_profile = load_candidate_profile()
        print(
            f"  Candidate profile: {paths.ai_candidate_profile_path()} "
            f"({len(candidate_profile)} chars)\n"
        )

        ai_t0 = time.monotonic()
        batches_processed = 0

        for batch_num, i in enumerate(
            range(0, ai_candidate_count, BATCH_SIZE), start=1
        ):
            batch = ai_scoring_jobs[i : i + BATCH_SIZE]
            batch_t0 = time.monotonic()
            batch_payload = batch_score_jobs(batch, candidate_profile)
            batch_sec = time.monotonic() - batch_t0

            if not batch_payload or not batch_payload.get("request_ok"):
                print(f"⚠️ Batch {batch_num} failed (skipping, {batch_sec:.1f}s)")
                continue

            normalized_results = batch_payload.get("results") or []
            valid_results, skipped_invalid = validate_ai_batch_results(
                normalized_results, batch_size=len(batch)
            )

            batches_processed += 1
            ai_results_applied += len(valid_results)
            print(
                f"✅ Batch {batch_num} Complete "
                f"(input_batch_size={len(batch)}, "
                f"parsed_result_count={batch_payload.get('parsed_result_count', 0)}, "
                f"valid_results_applied={len(valid_results)}, "
                f"skipped_invalid_results={skipped_invalid}, "
                f"normalization_strategy_used={batch_payload.get('normalization_strategy_used', 'unknown')}, "
                f"{batch_sec:.1f}s)"
            )

            for result in valid_results:
                idx = result["index"]
                ai_scoring_jobs[i + idx]["score"] = result["score"]
                ai_scoring_jobs[i + idx]["reason"] = result["reason"]
                ai_scoring_jobs[i + idx]["ai_status"] = "scored"

        ai_total_sec = time.monotonic() - ai_t0
        print(f"\n{ai_banner}")
        print("🤖 AI BATCH SCORING COMPLETE")
        print(f"{ai_banner}\n")
        print(f"✅ Total Batches Processed: {batches_processed}")
        print(f"✅ Total Jobs AI Scored: {ai_results_applied}")
        print(f"✅ Total Duration: {ai_total_sec:.1f}s\n")

    newly_ai_scored_jobs = [
        job for job in ai_scoring_jobs if job.get("ai_status") == "scored"
    ]
    new_ai_persistence_jobs = ai_scoring_jobs + pending_ai_jobs
    print(
        f"  Export composition (this session): up to {split_fully_processed} fully_processed "
        f"+ {len(new_ai_persistence_jobs)} AI-candidate persisted"
    )
    if ai_skipped_by_cap > 0:
        print(
            f"  AI candidates beyond cap (persisted, not scored): {ai_skipped_by_cap} "
            f"(DEBUG_LIMIT={DEBUG_LIMIT})"
        )

    pre_final_merge_count = len(fully_processed_jobs) + len(new_ai_persistence_jobs)

    fully_processed_by_key = {}
    for job in fully_processed_jobs:
        if not str(job.get("JOB_KEY", "")).strip():
            job["JOB_KEY"] = generate_job_key(job)
        merge_key = _production_final_merge_key(job)
        fully_processed_by_key[merge_key] = job

    dedup_final = {}

    for key, job in fully_processed_by_key.items():
        dedup_final[key] = job

    for job in new_ai_persistence_jobs:
        if not str(job.get("JOB_KEY", "")).strip():
            job["JOB_KEY"] = generate_job_key(job)
        merge_key = _production_final_merge_key(job)
        dedup_final[merge_key] = job

    session_export_jobs = list(dedup_final.values())

    session_export_jobs = sorted(
        session_export_jobs,
        key=lambda x: x.get("time_rank", 999)
    )

    final_recommendation_count = len(session_export_jobs)
    final_dedup_removed = pre_final_merge_count - final_recommendation_count
    unresolved_segments["unresolved_final_recommendations"] = list(session_export_jobs)
    unresolved_funnel = build_unresolved_identity_funnel(unresolved_segments)

    # =========================================================
    # 📊 PIPELINE METRICS DASHBOARD
    # =========================================================

    ai_scored_count = len(newly_ai_scored_jobs)

    log_job_identity_metrics(identity_metrics)

    continuity_metrics = collect_phase6_continuity_metrics(
        session_export_jobs
    )
    historical_upsert_trace: dict = {}

    log_section("📊 PIPELINE METRICS")

    print(f"📦 RAW JOBS COLLECTED:      {raw_jobs_count}")
    print(f"🎯 AFTER STAGE 1 FILTER:    {after_stage1_count}")
    print(f"🧹 AFTER DEDUPLICATION:     {dedup_jobs_count}")
    print(f"📄 Brand-new jobs (description stage): {description_jobs_count}")
    print(f"🤖 AI SCORED JOBS:          {ai_scored_count}")

    pipeline_banner = "=" * 60
    print(f"\n{pipeline_banner}")
    print("📊 PIPELINE SUMMARY")
    print(f"{pipeline_banner}\n")
    print("↓ Job Routing\n")
    print(f"✅ Fully Processed: {split_fully_processed}")
    print(f"🧠 Needs AI Only: {split_needs_ai_only}")
    print(f"🆕 Brand New Jobs: {split_brand_new}\n")
    print(
        "  Stage counts (raw → Stage 1 → dedup → descriptions → AI scored): "
        "see PIPELINE METRICS above\n"
    )
    print("↓ AI Pipeline\n")
    print(f"🧠 Needs-AI-Only Queue: {split_needs_ai_only}")
    print(
        f"🤖 AI Candidates: {ai_candidates_before_limit} (cap DEBUG_LIMIT={DEBUG_LIMIT})"
    )
    print(
        f"✅ AI Scored: {ai_results_applied} | "
        f"⏭️ Skipped by cap: {ai_skipped_by_cap}\n"
    )
    print(f"💾 Historical persistence cohort: {len(session_export_jobs)}")
    print(f"📄 Session export rows: {len(session_export_jobs)}")
    print(f"🤝 CRM sync cohort: {len(session_export_jobs)}")
    print(f"{pipeline_banner}\n")

    # =========================
    # 💾 SAVE OUTPUT
    # =========================
    log_section("🔬 RUNNING FINAL MERGE DEDUP")
    print(f"pre_final_merge_count: {pre_final_merge_count}")
    print(f"final_dedup_removed: {final_dedup_removed}")
    print(f"final_recommendation_count: {final_recommendation_count}")

    # =========================
    # 🧠 UPDATE HISTORICAL MEMORY (V2 + legacy dual-write on historical_jobs.csv)
    # Skipped when SQLITE_WRITE_PRIMARY=1 (SQLite dual-write is authoritative).
    # =========================
    update_historical_jobs(session_export_jobs, upsert_trace=historical_upsert_trace)

    print("final_merge_authority=v2_only")

    log_production_identity_health_summary(
        identity_metrics=identity_metrics,
        historical_lookup_trace=historical_lookup_trace,
        dedup_observability=dedup_observability,
        historical_upsert_trace=historical_upsert_trace,
        continuity_metrics=continuity_metrics,
        unresolved_funnel=unresolved_funnel,
        final_recommendation_count=final_recommendation_count,
        final_dedup_removed=final_dedup_removed,
    )

    # =========================
    # 🗄️ SQLITE DUAL-WRITE (Phase C) — before D2 export so current_jobs_view
    # has this run's job_observations when SQLITE_EXPORT_FROM_DB is enabled.
    # When SQLITE_WRITE_PRIMARY=1, dual-write is the authoritative persistence path.
    # =========================
    dual_write_report = dual_write_runtime_snapshot(
        jobs=session_export_jobs,
        persistence_cohort_count=len(session_export_jobs),
        run_started_at=pipeline_started_at,
        run_notes="phase_c_runtime_dual_write",
    )

    from db.write.engine import (
        export_crm_csv_enabled,
        export_descriptions_csv_enabled,
        export_historical_csv_enabled,
        export_jobs_csv_enabled,
        write_primary_enabled,
    )
    from db.write.csv_export import export_write_primary_csvs

    if write_primary_enabled():
        print("\n  SQLite write-primary: CSV persistence gated by SQLITE_EXPORT_* flags")
        export_write_primary_csvs(
            export_historical=export_historical_csv_enabled(),
            export_descriptions=export_descriptions_csv_enabled(),
            export_crm=export_crm_csv_enabled(),
        )

    if export_jobs_csv_enabled():
        save_to_csv_via_db_export(session_export_jobs)
    else:
        print("\n  jobs.csv export skipped (SQLITE_EXPORT_JOBS_CSV=0)")

    # =========================
    # 🤝 UPDATE RECRUITER CRM
    # =========================
    update_recruiter_crm(session_export_jobs)

    csv_counts = csv_runtime_counts()
    csv_ai_dist = csv_ai_status_dist()
    dual_write_report["csv_counts"] = {
        **csv_counts,
        "ai_status_scored": csv_ai_dist.get("scored", 0),
        "ai_status_skipped_by_cap": csv_ai_dist.get("skipped_by_cap", 0),
        "ai_status_pending": csv_ai_dist.get("pending", 0),
    }
    log_dual_write_summary(dual_write_report)
