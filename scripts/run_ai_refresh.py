#!/usr/bin/env python3
"""Refresh AI Evaluations — re-score existing jobs from SQLite (no acquisition)."""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
for entry in (str(_REPO_ROOT), str(_SRC)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

import paths  # noqa: E402
from agent.ai_scoring_orchestrator import run_batch_ai_scoring  # noqa: E402
from agent.job_identity import instrument_jobs_identity_v2  # noqa: E402
from db.bootstrap import ensure_database_ready  # noqa: E402
from db.listing_status import (  # noqa: E402
    MONITOR_RUN_STATUS_COMPLETED,
    MONITOR_RUN_STATUS_FAILED,
)
from db.read.ai_refresh_cohort import (  # noqa: E402
    AI_REFRESH_PRESET_BACKLOG,
    AI_REFRESH_PRESET_DISCOVERY,
    AI_REFRESH_PRESETS,
    load_ai_refresh_cohort,
    select_ai_refresh_cohort_rows,
)
from db.read.engine import get_read_session  # noqa: E402
from db.read.historical import load_historical_jobs_view_df  # noqa: E402
from db.services.ai_refresh_write import (  # noqa: E402
    finalize_ai_refresh_run,
    open_ai_refresh_run,
    persist_ai_refresh_scored_jobs,
)

ACQUISITION_LOCK = "/tmp/ai-job-agent-acquisition.lock"
AI_REFRESH_LOCK = "/tmp/ai-job-agent-ai-refresh.lock"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Refresh AI evaluations for existing jobs.")
    parser.add_argument(
        "--preset",
        choices=sorted(AI_REFRESH_PRESETS.keys()),
        default=AI_REFRESH_PRESET_BACKLOG,
        help="Cohort preset (default: backlog)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print cohort summary only; no OpenAI or DB writes",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Override DEBUG_LIMIT for this run (optional)",
    )
    return parser.parse_args()


def _acquisition_lock_held() -> bool:
    if not os.path.isfile(ACQUISITION_LOCK):
        return False
    try:
        import fcntl

        with open(ACQUISITION_LOCK, "a+", encoding="utf-8") as fp:
            try:
                fcntl.flock(fp.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(fp.fileno(), fcntl.LOCK_UN)
                return False
            except BlockingIOError:
                return True
    except OSError:
        return False


def _acquire_refresh_lock() -> object | None:
    import fcntl

    lock_fp = open(AI_REFRESH_LOCK, "a+", encoding="utf-8")
    try:
        fcntl.flock(lock_fp.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock_fp.close()
        return None
    lock_fp.seek(0)
    lock_fp.truncate()
    lock_fp.write(f"{os.getpid()}\n")
    lock_fp.flush()
    return lock_fp


def _release_refresh_lock(lock_fp: object | None) -> None:
    import fcntl

    if lock_fp is None:
        return
    if hasattr(lock_fp, "fileno"):
        try:
            fcntl.flock(lock_fp.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
    try:
        lock_fp.close()  # type: ignore[union-attr]
    except OSError:
        pass
    except AttributeError:
        pass
    try:
        os.unlink(AI_REFRESH_LOCK)
    except OSError:
        pass


def _redirect_run_log() -> tuple[Path | None, object | None, object | None]:
    """Tee stdout/stderr to logs/scheduled when interactive or env requests it."""
    env_path = os.environ.get("AI_REFRESH_LOG_FILE", "").strip()
    if env_path:
        path = Path(env_path)
    elif sys.stdout.isatty():
        log_dir = _REPO_ROOT / "logs" / "scheduled"
        log_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        path = log_dir / f"ai-refresh-{stamp}.log"
    else:
        return None, None, None
    path.parent.mkdir(parents=True, exist_ok=True)
    log_fp = open(path, "a", encoding="utf-8", buffering=1)
    prior_stdout, prior_stderr = sys.stdout, sys.stderr
    sys.stdout = log_fp
    sys.stderr = log_fp
    print(f"LOG_FILE={path}")
    print(f"AI Refresh started: {datetime.now(UTC).isoformat()}")
    return path, prior_stdout, prior_stderr


def _restore_run_log(prior: tuple[object | None, object | None]) -> None:
    prior_stdout, prior_stderr = prior
    if prior_stdout is not None:
        try:
            sys.stdout.flush()
            if hasattr(sys.stdout, "close"):
                sys.stdout.close()
        except (OSError, ValueError):
            pass
        sys.stdout = prior_stdout  # type: ignore[assignment]
    if prior_stderr is not None and prior_stderr is not prior_stdout:
        try:
            sys.stderr.flush()
            if hasattr(sys.stderr, "close"):
                sys.stderr.close()
        except (OSError, ValueError):
            pass
        sys.stderr = prior_stderr  # type: ignore[assignment]


def main() -> int:
    args = _parse_args()
    preset = str(args.preset).strip().lower()

    if not os.environ.get("OPENAI_API_KEY", "").strip():
        print("ERROR: OPENAI_API_KEY is not set.", file=sys.stderr)
        return 1

    if _acquisition_lock_held():
        print(
            "SKIP: acquisition lock held; defer AI refresh until acquisition completes.",
            file=sys.stderr,
        )
        return 0

    lock_fp = _acquire_refresh_lock()
    if lock_fp is None:
        print("SKIP: another AI refresh run is already in progress.", file=sys.stderr)
        return 0

    run_id: int | None = None
    cohort_size = 0
    eligible_count = 0
    skipped_no_description = 0
    started = time.monotonic()
    prior_stdio: tuple[object | None, object | None] = (None, None)

    try:
        _, prior_stdout, prior_stderr = _redirect_run_log()
        prior_stdio = (prior_stdout, prior_stderr)

        if args.limit is not None:
            os.environ["DEBUG_LIMIT"] = str(int(args.limit))

        ensure_database_ready()

        with get_read_session() as session:
            if args.dry_run:
                df = load_historical_jobs_view_df(session)
                rows = select_ai_refresh_cohort_rows(df, preset)
                jobs, skipped = load_ai_refresh_cohort(session, preset)
                print(f"Preset: {AI_REFRESH_PRESETS.get(preset, preset)} ({preset})")
                print(f"Cohort rows matched: {len(rows)}")
                print(f"Eligible with description: {len(jobs)}")
                print(f"Skipped (no description): {skipped}")
                for row in rows[:10]:
                    print(f"  - {row.get('JOB_KEY_V2')} | {row.get('title')} @ {row.get('company')}")
                if len(rows) > 10:
                    print(f"  ... and {len(rows) - 10} more")
                return 0

            jobs, skipped_no_description = load_ai_refresh_cohort(session, preset)

        cohort_size = len(jobs) + skipped_no_description
        eligible_count = len(jobs)
        if not jobs:
            print("No eligible jobs to score for this preset.")
            return 0

        instrument_jobs_identity_v2(jobs)

        run_id = open_ai_refresh_run(preset)
        started = time.monotonic()

        print(f"\n=== AI Refresh ({AI_REFRESH_PRESETS.get(preset, preset)}) ===")
        print(f"Profile: {paths.ai_candidate_profile_path()}")
        print(f"Eligible jobs: {eligible_count}")
        print(f"Skipped (no description): {skipped_no_description}\n")

        scoring_result = run_batch_ai_scoring(jobs, verbose=True)
        scored_jobs = [
            job
            for job in scoring_result.ai_scoring_jobs
            if job.get("ai_status") == "scored"
        ]
        persist_result = persist_ai_refresh_scored_jobs(run_id, scored_jobs)

        stats = scoring_result.stats
        error_summary: str | None = None
        if persist_result.skipped > 0:
            error_summary = (
                f"Persist skipped {persist_result.skipped} of "
                f"{persist_result.scoring_candidates} scored job(s)"
            )
        finalize_ai_refresh_run(
            run_id,
            status=MONITOR_RUN_STATUS_COMPLETED,
            cohort_size=cohort_size,
            eligible_count=eligible_count,
            scored_count=persist_result.persisted,
            persist_skipped_count=persist_result.skipped,
            skipped_no_description=skipped_no_description,
            skipped_by_cap_count=stats.ai_skipped_by_cap,
            batch_failures=stats.batch_failures,
            duration_sec=time.monotonic() - started,
            error_summary=error_summary,
        )

        print("\n=== AI Refresh complete ===")
        print(f"Run id: {run_id}")
        print(f"Scored (in-memory): {len(scored_jobs)}")
        print(f"Persisted: {persist_result.persisted}")
        if persist_result.skipped > 0:
            print(f"Persist skipped: {persist_result.skipped}")
        print(f"Skipped by cap: {stats.ai_skipped_by_cap}")
        print(f"Batch failures: {stats.batch_failures}")
        return 0
    except Exception as exc:
        if run_id is not None:
            finalize_ai_refresh_run(
                run_id,
                status=MONITOR_RUN_STATUS_FAILED,
                cohort_size=cohort_size,
                eligible_count=eligible_count,
                scored_count=0,
                persist_skipped_count=0,
                skipped_no_description=skipped_no_description,
                skipped_by_cap_count=0,
                batch_failures=0,
                duration_sec=time.monotonic() - started,
                error_summary=str(exc),
            )
        print(f"ERROR: AI refresh failed: {exc}", file=sys.stderr)
        return 1
    finally:
        _restore_run_log(prior_stdio)
        _release_refresh_lock(lock_fp)


if __name__ == "__main__":
    raise SystemExit(main())
