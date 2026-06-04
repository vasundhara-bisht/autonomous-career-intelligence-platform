import os
from datetime import datetime

import pandas as pd

import paths


# =========================================================
# 🧠 GENERATE STABLE RECRUITER KEY
# =========================================================
def generate_recruiter_key(name):
    return str(name).strip().lower()


CRM_INTERACTION_COLS = {
    "last_outreach_date": "",
    "last_response_date": "",
    "touchpoint_count": 0,
    "last_interaction_note": "",
}

CRM_OPTIONAL_RECRUITER_COLS = {
    "recruiter_title": "",
    "recruiter_company": "",
}


def _clean_str(value) -> str:
    return str(value or "").strip()


def _recruiter_fields_from_job(job: dict) -> dict[str, str]:
    """Resolve recruiter identity from job (Instahyre + LinkedIn shapes)."""
    name = _clean_str(job.get("recruiter_name")) or _clean_str(job.get("hiring_manager"))
    title = _clean_str(job.get("recruiter_title"))
    company = _clean_str(job.get("recruiter_company"))
    return {
        "recruiter_name": name,
        "recruiter_title": title,
        "recruiter_company": company,
    }


def _is_valid_recruiter_name(name: str) -> bool:
    if not name:
        return False
    return name.lower() not in ("not specified", "unknown", "nan")


def _row_dict(df: pd.DataFrame, idx) -> dict:
    return {col: df.at[idx, col] for col in df.columns}


def _existing_row_changed(
    before: dict,
    after: dict,
    *,
    track_cols: list[str],
) -> bool:
    for col in track_cols:
        if col not in before and col not in after:
            continue
        if _clean_str(before.get(col)) != _clean_str(after.get(col)):
            return True
    return False


# =========================================================
# 📦 UPDATE RECRUITER CRM
# =========================================================
def _recruiter_crm_summary_from_jobs(jobs) -> tuple[int, int, int]:
    """Count cohort recruiters for write-primary summary (no CSV I/O)."""
    current_run_recruiters: set[str] = set()
    for job in jobs:
        fields = _recruiter_fields_from_job(job)
        recruiter_name = fields["recruiter_name"]
        if not _is_valid_recruiter_name(recruiter_name):
            continue
        current_run_recruiters.add(generate_recruiter_key(recruiter_name))
    return len(current_run_recruiters), 0, 0


def update_recruiter_crm(jobs):
    from db.write.engine import write_primary_enabled

    if write_primary_enabled():
        cohort_count, _, _ = _recruiter_crm_summary_from_jobs(jobs)
        total = 0
        try:
            from db.bootstrap import ensure_database_ready
            from db.engine import get_session
            from db.models.schema import Recruiter
            from sqlalchemy import func, select

            ensure_database_ready()
            with get_session() as session:
                total = session.execute(
                    select(func.count()).select_from(Recruiter)
                ).scalar_one()
        except Exception:
            pass
        print("\n" + "=" * 60)
        print("🤝 RECRUITER CRM SYNC COMPLETE")
        print("write_primary=1 (SQLite authoritative; CSV export optional)")
        print(f"cohort_recruiters={cohort_count}")
        print(f"👤 Total Recruiters (DB)={total}")
        print("=" * 60)
        return

    CRM_FILE = paths.recruiter_crm_csv()
    STALE_RECRUITER_DAYS = 30
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    current_run_recruiters: set[str] = set()
    new_recruiters_added = 0
    existing_recruiters_updated = 0

    if CRM_FILE.is_file():
        crm_df = pd.read_csv(str(CRM_FILE))
    else:
        crm_df = pd.DataFrame(
            columns=[
                "RECRUITER_KEY",
                "recruiter_name",
                "current_company",
                "source",
                "first_seen",
                "last_seen",
                "jobs_connected",
                "recruiter_stage",
                "outreach_sent",
                "recruiter_replied",
                "notes",
                "last_outreach_date",
                "last_response_date",
                "touchpoint_count",
                "last_interaction_note",
                "currently_active",
            ]
        )

    for col, default in CRM_INTERACTION_COLS.items():
        if col not in crm_df.columns:
            crm_df[col] = default

    for col, default in CRM_OPTIONAL_RECRUITER_COLS.items():
        if col not in crm_df.columns:
            crm_df[col] = default

    track_cols = [
        "recruiter_name",
        "current_company",
        "source",
        "recruiter_title",
        "recruiter_company",
        "last_seen",
        "jobs_connected",
        "currently_active",
    ]

    for job in jobs:
        fields = _recruiter_fields_from_job(job)
        recruiter_name = fields["recruiter_name"]
        if not _is_valid_recruiter_name(recruiter_name):
            continue

        recruiter_key = generate_recruiter_key(recruiter_name)
        current_run_recruiters.add(recruiter_key)

        existing_match = crm_df[crm_df["RECRUITER_KEY"] == recruiter_key]

        if existing_match.empty:
            new_row = {
                "RECRUITER_KEY": recruiter_key,
                "recruiter_name": recruiter_name,
                "current_company": job.get("company", ""),
                "source": job.get("source", ""),
                "first_seen": now,
                "last_seen": now,
                "jobs_connected": 1,
                "recruiter_stage": "discovered",
                "outreach_sent": False,
                "recruiter_replied": False,
                "notes": "",
                "last_outreach_date": "",
                "last_response_date": "",
                "touchpoint_count": 0,
                "last_interaction_note": "",
                "currently_active": True,
                "recruiter_title": fields["recruiter_title"],
                "recruiter_company": fields["recruiter_company"],
            }
            crm_df = pd.concat([crm_df, pd.DataFrame([new_row])], ignore_index=True)
            new_recruiters_added += 1
            continue

        idx = existing_match.index[0]
        before = _row_dict(crm_df, idx)

        employer = _clean_str(job.get("company"))
        if employer:
            crm_df.at[idx, "current_company"] = employer

        source = _clean_str(job.get("source"))
        if source:
            crm_df.at[idx, "source"] = source

        if fields["recruiter_title"]:
            crm_df.at[idx, "recruiter_title"] = fields["recruiter_title"]

        if fields["recruiter_company"]:
            crm_df.at[idx, "recruiter_company"] = fields["recruiter_company"]

        crm_df.at[idx, "last_seen"] = now
        crm_df.at[idx, "currently_active"] = True
        crm_df.at[idx, "jobs_connected"] = int(crm_df.at[idx, "jobs_connected"]) + 1

        after = _row_dict(crm_df, idx)
        if _existing_row_changed(before, after, track_cols=track_cols):
            existing_recruiters_updated += 1

    stale_mutations = 0
    for idx, row in crm_df.iterrows():
        recruiter_key = row["RECRUITER_KEY"]
        before_active = bool(row.get("currently_active"))

        if recruiter_key in current_run_recruiters:
            crm_df.at[idx, "currently_active"] = True
            if not before_active:
                stale_mutations += 1
            continue

        try:
            last_seen = datetime.strptime(str(row["last_seen"]), "%Y-%m-%d %H:%M:%S")
            days_since_seen = (datetime.now() - last_seen).days
            if days_since_seen >= STALE_RECRUITER_DAYS:
                crm_df.at[idx, "currently_active"] = False
                if before_active:
                    stale_mutations += 1
        except Exception:
            crm_df.at[idx, "currently_active"] = False
            if before_active:
                stale_mutations += 1

    crm_df = crm_df.drop_duplicates(subset=["RECRUITER_KEY"])
    crm_df = crm_df.sort_values(
        by=["currently_active", "last_seen"],
        ascending=[False, False],
    )

    mutations = new_recruiters_added + existing_recruiters_updated + stale_mutations
    if mutations > 0:
        crm_df.to_csv(str(CRM_FILE), index=False)

    print("\n" + "=" * 60)
    print("🤝 RECRUITER CRM SYNC COMPLETE")
    print(f"new_recruiters_added={new_recruiters_added}")
    print(f"existing_recruiters_updated={existing_recruiters_updated}")
    print(f"👤 Total Recruiters={len(crm_df)}")
    if mutations > 0:
        print("RECRUITER CRM UPDATED")
    else:
        print("(no changes)")
    print("=" * 60)
