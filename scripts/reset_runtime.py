#!/usr/bin/env python3
"""Profile-driven runtime reset engine.

This module is intentionally file/resource oriented so future SQLite/Postgres
backends can replace the resource implementations without changing reset
profile semantics.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
for entry in (str(_REPO_ROOT), str(_SRC)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

import paths
from agent.bootstrap_schema import (
    HISTORICAL_UI_EXTENSION_COLUMNS,
    _read_template_header,
    historical_jobs_schema_columns,
    job_descriptions_schema_columns,
    jobs_csv_schema_columns,
    linkedin_query_empty_state,
    recruiter_crm_schema_columns,
    write_empty_csv,
    write_empty_json,
)


EMPTY_PLAYWRIGHT_STORAGE_STATE = {"cookies": [], "origins": []}


@dataclass(frozen=True)
class ResetResource:
    name: str
    kind: str
    path_fn: Callable[[], Path]
    schema_fn: Callable[[bool], Any]
    reset_fn: Callable[[Path, Any], None]

    def path(self) -> Path:
        return self.path_fn()

    def schema(self, use_template_fallback: bool) -> Any:
        return self.schema_fn(use_template_fallback)

    def reset(self, *, use_template_fallback: bool) -> None:
        self.reset_fn(self.path(), self.schema(use_template_fallback))


@dataclass(frozen=True)
class ResetProfile:
    name: str
    description: str
    reset_resources: tuple[str, ...]


def _historical_schema(use_template_fallback: bool) -> list[str]:
    if use_template_fallback:
        cols = _read_template_header("historical_jobs.header.csv")
        for col in HISTORICAL_UI_EXTENSION_COLUMNS:
            if col not in cols:
                cols.append(col)
        return cols
    return historical_jobs_schema_columns(include_ui_extensions=True)


def _jobs_schema(use_template_fallback: bool) -> list[str]:
    if use_template_fallback:
        return _read_template_header("jobs.header.csv")
    return jobs_csv_schema_columns(union_with_existing_file=False)


def _job_descriptions_schema(use_template_fallback: bool) -> list[str]:
    if use_template_fallback:
        return _read_template_header("job_descriptions.header.csv")
    return job_descriptions_schema_columns()


def _recruiter_crm_schema(_use_template_fallback: bool) -> list[str]:
    return recruiter_crm_schema_columns()


def _linkedin_query_state_schema(_use_template_fallback: bool) -> dict[str, Any]:
    return linkedin_query_empty_state()


def _auth_state_schema(_use_template_fallback: bool) -> dict[str, Any]:
    return dict(EMPTY_PLAYWRIGHT_STORAGE_STATE)


def _write_csv(path: Path, columns: list[str]) -> None:
    write_empty_csv(path, columns)


def _write_json(path: Path, data: dict[str, Any]) -> None:
    write_empty_json(path, data)


RESOURCES: dict[str, ResetResource] = {
    "historical_jobs": ResetResource(
        "historical_jobs",
        "csv",
        paths.historical_jobs_csv,
        _historical_schema,
        _write_csv,
    ),
    "jobs": ResetResource(
        "jobs",
        "csv",
        paths.jobs_csv,
        _jobs_schema,
        _write_csv,
    ),
    "job_descriptions": ResetResource(
        "job_descriptions",
        "csv",
        paths.job_descriptions_csv,
        _job_descriptions_schema,
        _write_csv,
    ),
    "linkedin_query_state": ResetResource(
        "linkedin_query_state",
        "json",
        paths.linkedin_query_state_json,
        _linkedin_query_state_schema,
        _write_json,
    ),
    "recruiter_crm": ResetResource(
        "recruiter_crm",
        "csv",
        paths.recruiter_crm_csv,
        _recruiter_crm_schema,
        _write_csv,
    ),
    "linkedin_auth": ResetResource(
        "linkedin_auth",
        "auth_json",
        paths.linkedin_auth_json,
        _auth_state_schema,
        _write_json,
    ),
    "instahyre_auth": ResetResource(
        "instahyre_auth",
        "auth_json",
        paths.instahyre_auth_json,
        _auth_state_schema,
        _write_json,
    ),
}

AUTH_RESOURCES = ("linkedin_auth", "instahyre_auth")

PROFILES: dict[str, ResetProfile] = {
    "bootstrap": ResetProfile(
        name="bootstrap",
        description="Clean bootstrap validation; reset job memory, descriptions, query state, and CRM.",
        reset_resources=(
            "historical_jobs",
            "jobs",
            "job_descriptions",
            "linkedin_query_state",
            "recruiter_crm",
        ),
    ),
    "acquisition": ResetProfile(
        name="acquisition",
        description="Acquisition-only reset; preserve historical memory, descriptions, CRM, and auth.",
        reset_resources=("jobs", "linkedin_query_state"),
    ),
    "crm-preserving": ResetProfile(
        name="crm-preserving",
        description="Legacy production-safe reset; preserve recruiter CRM and auth.",
        reset_resources=(
            "historical_jobs",
            "jobs",
            "job_descriptions",
            "linkedin_query_state",
        ),
    ),
    "full": ResetProfile(
        name="full",
        description="Full runtime reset except auth by default.",
        reset_resources=(
            "historical_jobs",
            "jobs",
            "job_descriptions",
            "linkedin_query_state",
            "recruiter_crm",
        ),
    ),
}


def _rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(paths.REPO_ROOT))
    except ValueError:
        return str(path)


def _git_head() -> str:
    try:
        return (
            subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                cwd=paths.REPO_ROOT,
                stderr=subprocess.DEVNULL,
            )
            .decode()
            .strip()
        )
    except Exception:
        return ""


def _running_warnings() -> list[str]:
    checks = (
        ("main.py", ["pgrep", "-f", "python.*main.py"]),
        ("Streamlit", ["pgrep", "-f", "streamlit.*app.py"]),
    )
    out: list[str] = []
    for label, cmd in checks:
        try:
            res = subprocess.run(
                cmd,
                cwd=paths.REPO_ROOT,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            if res.returncode == 0:
                out.append(f"{label} may be running. Stop it before applying reset.")
        except FileNotFoundError:
            continue
    return out


def _row_count(path: Path) -> int | None:
    if not path.is_file() or path.suffix.lower() != ".csv":
        return None
    try:
        return len(pd.read_csv(path))
    except Exception:
        return None


def _file_meta(resource: ResetResource) -> dict[str, Any]:
    path = resource.path()
    meta: dict[str, Any] = {
        "resource": resource.name,
        "path": _rel(path),
        "kind": resource.kind,
        "exists": path.exists(),
    }
    if path.exists():
        meta["bytes"] = path.stat().st_size
    rows = _row_count(path)
    if rows is not None:
        meta["row_count"] = rows
    return meta


def _schema_snapshot(use_template_fallback: bool) -> dict[str, Any]:
    return {
        name: res.schema(use_template_fallback)
        for name, res in RESOURCES.items()
        if res.kind != "auth_json"
    }


def _archive_dir(archive_id: str) -> Path:
    return (paths.ARCHIVE_DIR / archive_id).resolve()


def _validate_archive(archive_id: str) -> Path:
    if not archive_id:
        raise SystemExit("ERROR: --archive-id is required.")
    archive_dir = _archive_dir(archive_id)
    manifest = archive_dir / "MANIFEST.json"
    if not manifest.is_file():
        raise SystemExit(
            f"ERROR: Missing archive manifest: {_rel(manifest)}\n"
            "Run ./scripts/archive_state.sh first."
        )
    return manifest


def _sqlite_tables_for_profile(profile_name: str) -> list[str]:
    from db.reset_sqlite import tables_for_profile

    return list(tables_for_profile(profile_name))


def _build_plan(
    *,
    profile_name: str,
    reset_auth: bool,
    use_template_fallback: bool,
    archive_id: str,
) -> dict[str, Any]:
    if profile_name not in PROFILES:
        raise SystemExit(f"ERROR: unknown profile {profile_name!r}")
    profile = PROFILES[profile_name]
    reset_names = list(profile.reset_resources)
    if reset_auth:
        reset_names.extend([name for name in AUTH_RESOURCES if name not in reset_names])

    preserve_names = [name for name in RESOURCES if name not in set(reset_names)]
    reset_resources = [RESOURCES[name] for name in reset_names]
    preserve_resources = [RESOURCES[name] for name in preserve_names]

    return {
        "archive_id": archive_id,
        "profile": profile.name,
        "description": profile.description,
        "auth_reset": bool(reset_auth),
        "use_template_fallback": bool(use_template_fallback),
        "sqlite_enabled": _sqlite_reset_enabled(),
        "sqlite_tables": _sqlite_tables_for_profile(profile.name),
        "warnings": _running_warnings(),
        "reset": [_file_meta(res) for res in reset_resources],
        "preserve": [_file_meta(res) for res in preserve_resources],
        "schemas": {
            res.name: res.schema(use_template_fallback)
            for res in reset_resources
            if res.kind in ("csv", "json")
        },
        "resulting_query_state": linkedin_query_empty_state(),
    }


def _sqlite_reset_enabled() -> bool:
    from db.reset_sqlite import sqlite_reset_enabled

    return sqlite_reset_enabled()


def _print_plan(plan: dict[str, Any], *, dry_run: bool) -> None:
    mode = "DRY RUN" if dry_run else "RESET PLAN"
    print(f"\n{mode}: {plan['profile']}")
    print(f"Description: {plan['description']}")
    print(f"Archive ID: {plan['archive_id']}")
    print(f"Auth reset: {'yes' if plan['auth_reset'] else 'no'}")
    if plan["use_template_fallback"]:
        print("Schema mode: template fallback")
    else:
        print("Schema mode: dynamic code-derived schemas")

    if plan["warnings"]:
        print("\nWarnings:")
        for msg in plan["warnings"]:
            print(f"  - {msg}")

    print("\nWill reset:")
    for item in plan["reset"]:
        rows = f", rows={item['row_count']}" if "row_count" in item else ""
        exists = "exists" if item["exists"] else "missing"
        print(f"  - {item['path']} ({item['kind']}, {exists}{rows})")

    print("\nWill preserve:")
    for item in plan["preserve"]:
        rows = f", rows={item['row_count']}" if "row_count" in item else ""
        exists = "exists" if item["exists"] else "missing"
        print(f"  - {item['path']} ({item['kind']}, {exists}{rows})")

    print("\nResulting schemas:")
    for name, schema in plan["schemas"].items():
        if isinstance(schema, list):
            print(f"  - {name}: {len(schema)} columns")
            print(f"    {', '.join(schema)}")
        else:
            print(f"  - {name}: {json.dumps(schema, sort_keys=True)}")

    print("\nResulting LinkedIn query state:")
    print(json.dumps(plan["resulting_query_state"], indent=2))

    if plan.get("sqlite_enabled"):
        print("\nSQLite truncate (SQLITE_ENABLED=1):")
        for table in plan.get("sqlite_tables", []):
            print(f"  - {table}")
    else:
        print("\nSQLite truncate: skipped (SQLITE_ENABLED=0)")

    if dry_run:
        print("\nDry run only - no files modified.")


def _confirm_or_abort(
    *,
    profile: str,
    reset_auth: bool,
    no_confirm: bool,
    confirm_reset_auth: bool,
) -> None:
    if no_confirm:
        if reset_auth and not confirm_reset_auth:
            raise SystemExit(
                "ERROR: --reset-auth with --no-confirm requires --confirm-reset-auth."
            )
        return

    expected = f"RESET {profile}"
    entered = input(f"Type {expected} to continue: ").strip()
    if entered != expected:
        raise SystemExit("Aborted.")

    if reset_auth:
        entered_auth = input("Type RESET AUTH to reset scraper sessions: ").strip()
        if entered_auth != "RESET AUTH":
            raise SystemExit("Aborted.")


def _apply_reset(
    *,
    plan: dict[str, Any],
    use_template_fallback: bool,
    archive_dir: Path,
) -> dict[str, Any]:
    reset_names = [item["resource"] for item in plan["reset"]]
    for name in reset_names:
        RESOURCES[name].reset(use_template_fallback=use_template_fallback)
        print(f"reset: {RESOURCES[name].path().name}")

    sqlite_truncated: list[str] = []
    if plan.get("sqlite_enabled"):
        from db.reset_sqlite import truncate_profile_tables

        sqlite_truncated = truncate_profile_tables(
            plan["profile"],
            dry_run=False,
        )

    audit = {
        "applied_at": datetime.now(timezone.utc).isoformat(),
        "profile": plan["profile"],
        "archive_id": plan["archive_id"],
        "git_head": _git_head(),
        "auth_reset": plan["auth_reset"],
        "use_template_fallback": plan["use_template_fallback"],
        "files_reset": plan["reset"],
        "files_preserved": plan["preserve"],
        "row_counts_before_reset": {
            item["resource"]: item.get("row_count")
            for item in [*plan["reset"], *plan["preserve"]]
            if "row_count" in item
        },
        "schema_snapshot": _schema_snapshot(use_template_fallback),
        "sqlite_tables_truncated": sqlite_truncated,
    }
    out = archive_dir / "RESET_APPLIED.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(audit, f, indent=2)
        f.write("\n")
    print(f"Wrote {_rel(out)}")
    return audit


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Profile-driven runtime reset")
    parser.add_argument("--archive-id", required=True, help="Archive ID from archive_state.sh")
    parser.add_argument(
        "--profile",
        required=True,
        choices=sorted(PROFILES),
        help="Reset profile to apply",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print plan only")
    parser.add_argument("--no-confirm", action="store_true", help="Skip interactive confirmation")
    parser.add_argument(
        "--use-template-fallback",
        action="store_true",
        help="Use scripts/templates/*.header.csv schemas",
    )
    parser.add_argument(
        "--reset-auth",
        action="store_true",
        help="Also reset LinkedIn and Instahyre Playwright storage state",
    )
    parser.add_argument(
        "--confirm-reset-auth",
        action="store_true",
        help="Required with --reset-auth --no-confirm",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    manifest = _validate_archive(args.archive_id)
    archive_dir = manifest.parent
    print(f"Archive verified: {_rel(manifest)}")

    plan = _build_plan(
        profile_name=args.profile,
        reset_auth=args.reset_auth,
        use_template_fallback=args.use_template_fallback,
        archive_id=args.archive_id,
    )
    _print_plan(plan, dry_run=args.dry_run)

    if args.dry_run:
        if plan.get("sqlite_enabled"):
            from db.reset_sqlite import truncate_profile_tables

            truncate_profile_tables(plan["profile"], dry_run=True)
        return 0

    _confirm_or_abort(
        profile=args.profile,
        reset_auth=args.reset_auth,
        no_confirm=args.no_confirm,
        confirm_reset_auth=args.confirm_reset_auth,
    )
    _apply_reset(
        plan=plan,
        use_template_fallback=args.use_template_fallback,
        archive_dir=archive_dir,
    )
    print("Reset complete.")
    print("Done. Next: python main.py  then  python3 scripts/validate_bootstrap.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
