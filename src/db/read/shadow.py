"""CSV vs SQLite read-model shadow comparisons (D0)."""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from db.read.contracts import (
    HISTORICAL_SHADOW_COMPARE_COLUMNS,
    JOBS_CSV_METADATA_COLUMNS,
    JOBS_SHADOW_COMPARE_COLUMNS,
)
from db.read.transforms import normalize_key


@dataclass
class ShadowReport:
    name: str
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    stats: dict[str, int | str] = field(default_factory=dict)

    def ok(self) -> bool:
        return not self.failures


def _read_jobs_csv(path) -> pd.DataFrame:
    if not path.is_file() or path.stat().st_size == 0:
        return pd.DataFrame()
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def _index_by_v2(df: pd.DataFrame) -> dict[str, pd.Series]:
    if df.empty or "JOB_KEY_V2" not in df.columns:
        return {}
    out: dict[str, pd.Series] = {}
    for _, row in df.iterrows():
        key = normalize_key(row.get("JOB_KEY_V2"))
        if key:
            out[key] = row
    return out


def compare_jobs_csv_to_view(
    jobs_csv: pd.DataFrame,
    view_df: pd.DataFrame,
    *,
    cohort_keys: set[str] | None = None,
) -> ShadowReport:
    report = ShadowReport(name="jobs_csv_vs_current_jobs_view")
    csv_index = _index_by_v2(jobs_csv)
    view_index = _index_by_v2(view_df)

    csv_keys = set(csv_index)
    view_keys = set(view_index)
    if cohort_keys is not None:
        view_keys = view_keys & cohort_keys

    missing_in_view = sorted(csv_keys - view_keys)
    extra_in_view = sorted(view_keys - csv_keys)

    report.stats["csv_keys"] = len(csv_keys)
    report.stats["view_keys"] = len(view_keys)
    report.stats["missing_in_view"] = len(missing_in_view)
    report.stats["extra_in_view"] = len(extra_in_view)

    if missing_in_view:
        preview = ", ".join(missing_in_view[:8])
        suffix = "..." if len(missing_in_view) > 8 else ""
        report.failures.append(
            f"jobs.csv keys missing from current_jobs_view ({len(missing_in_view)}): "
            f"{preview}{suffix}"
        )

    if extra_in_view:
        preview = ", ".join(extra_in_view[:8])
        suffix = "..." if len(extra_in_view) > 8 else ""
        report.warnings.append(
            f"current_jobs_view keys not in jobs.csv ({len(extra_in_view)}): "
            f"{preview}{suffix}"
        )

    mismatches = 0
    for key in sorted(csv_keys & view_keys):
        csv_row = csv_index[key]
        view_row = view_index[key]
        for col in JOBS_SHADOW_COMPARE_COLUMNS:
            if col not in csv_row.index or col not in view_row.index:
                continue
            csv_val = str(csv_row.get(col, "")).strip()
            view_val = str(view_row.get(col, "")).strip()
            if col == "ai_score":
                try:
                    csv_num = float(csv_val) if csv_val else None
                except ValueError:
                    csv_num = None
                try:
                    view_num = float(view_val) if view_val else None
                except ValueError:
                    view_num = None
                if csv_num is None and view_num is None:
                    continue
                if csv_num is not None and view_num is not None and abs(csv_num - view_num) < 0.001:
                    continue
                mismatches += 1
                break
            elif col == "ai_status":
                if csv_val.lower() != view_val.lower():
                    mismatches += 1
                    break
            elif csv_val != view_val:
                mismatches += 1
                break

    report.stats["field_mismatches"] = mismatches
    if mismatches:
        report.failures.append(f"jobs.csv field mismatches on shared columns ({mismatches})")

    # Metadata columns only persisted in CSV today
    for col in JOBS_CSV_METADATA_COLUMNS:
        if col not in jobs_csv.columns:
            continue
        filled = jobs_csv[col].fillna("").astype(str).str.strip().ne("").sum()
        if filled:
            report.warnings.append(
                f"jobs.csv has {filled} row(s) with {col} (not stored per-job in SQLite jobs table)"
            )

    return report


def compare_historical_csv_to_view(
    historical_csv: pd.DataFrame,
    view_df: pd.DataFrame,
) -> ShadowReport:
    report = ShadowReport(name="historical_csv_vs_historical_jobs_view")
    csv_index = _index_by_v2(historical_csv)
    view_index = _index_by_v2(view_df)

    csv_keys = set(csv_index)
    view_keys = set(view_index)

    report.stats["csv_keys"] = len(csv_keys)
    report.stats["view_keys"] = len(view_keys)

    missing_in_view = sorted(csv_keys - view_keys)
    extra_in_view = sorted(view_keys - csv_keys)

    if missing_in_view:
        report.failures.append(
            f"historical CSV keys missing from historical_jobs_view ({len(missing_in_view)})"
        )
    if extra_in_view:
        report.warnings.append(
            f"historical_jobs_view keys not in CSV ({len(extra_in_view)}); "
            "cumulative DB superset possible"
        )

    mismatches = 0
    for key in sorted(csv_keys & view_keys):
        csv_row = csv_index[key]
        view_row = view_index[key]
        for col in HISTORICAL_SHADOW_COMPARE_COLUMNS:
            if col not in csv_row.index or col not in view_row.index:
                continue
            csv_val = str(csv_row.get(col, "")).strip()
            view_val = str(view_row.get(col, "")).strip()
            if col == "ai_score":
                try:
                    csv_num = float(csv_val) if csv_val else None
                except ValueError:
                    csv_num = None
                try:
                    view_num = float(view_val) if view_val else None
                except ValueError:
                    view_num = None
                if csv_num is None and view_num is None:
                    continue
                if csv_num is not None and view_num is not None and abs(csv_num - view_num) < 0.001:
                    continue
                mismatches += 1
                break
            elif col == "ai_status":
                if csv_val.lower() != view_val.lower():
                    mismatches += 1
                    break
            elif csv_val != view_val:
                mismatches += 1
                break

    report.stats["field_mismatches"] = mismatches
    if mismatches:
        report.failures.append(
            f"historical CSV field mismatches on shared columns ({mismatches})"
        )

    return report
