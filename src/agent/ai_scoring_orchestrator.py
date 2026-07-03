"""Shared AI batch scoring orchestration (acquisition + AI refresh)."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import paths
from agent.ai_batch_scorer import batch_score_jobs, validate_ai_batch_results
from agent.ai_runtime_config import resolve_batch_size, resolve_debug_limit
from agent.profile_loader import load_candidate_profile


@dataclass
class BatchScoringStats:
    ai_candidates_before_limit: int = 0
    ai_capped_count: int = 0
    ai_skipped_by_cap: int = 0
    debug_limit: int = 0
    batch_size: int = 0
    ai_candidate_count: int = 0
    batches_processed: int = 0
    ai_results_applied: int = 0
    batch_failures: int = 0
    ai_total_sec: float = 0.0


@dataclass
class BatchScoringResult:
    ai_scoring_jobs: list[dict]
    pending_ai_jobs: list[dict]
    persistent_jobs: list[dict]
    stats: BatchScoringStats = field(default_factory=BatchScoringStats)


def _prepare_scoring_queues(
    jobs: list[dict],
    *,
    apply_debug_limit: bool,
    reset_scores: bool,
) -> tuple[list[dict], list[dict], list[dict], BatchScoringStats]:
    stats = BatchScoringStats()
    stats.ai_candidates_before_limit = len(jobs)
    debug_limit = resolve_debug_limit() if apply_debug_limit else len(jobs)
    stats.debug_limit = debug_limit
    stats.ai_capped_count = min(stats.ai_candidates_before_limit, debug_limit)
    stats.ai_skipped_by_cap = max(0, stats.ai_candidates_before_limit - debug_limit)

    persistent_jobs = list(jobs)
    ai_scoring_jobs = persistent_jobs[:debug_limit]
    pending_ai_jobs = persistent_jobs[debug_limit:]

    if reset_scores:
        for job in persistent_jobs:
            job.pop("score", None)
            job.pop("ai_score", None)
            job["reason"] = ""
            job["ai_status"] = "pending"
        for job in pending_ai_jobs:
            job["ai_status"] = "skipped_by_cap"

    stats.ai_candidate_count = len(ai_scoring_jobs)
    stats.batch_size = resolve_batch_size()
    return ai_scoring_jobs, pending_ai_jobs, persistent_jobs, stats


def run_batch_ai_scoring(
    jobs: list[dict],
    *,
    apply_debug_limit: bool = True,
    reset_scores: bool = True,
    verbose: bool = True,
) -> BatchScoringResult:
    """
    Run OpenAI batch scoring on in-memory job dicts.

    Caller is responsible for sorting (e.g. by time_rank) before invoke.
    """
    ai_scoring_jobs, pending_ai_jobs, persistent_jobs, stats = _prepare_scoring_queues(
        jobs,
        apply_debug_limit=apply_debug_limit,
        reset_scores=reset_scores,
    )

    if verbose:
        print("\n--- AI scoring cap (DEBUG_LIMIT) ---")
        print(f"  Total AI candidates: {stats.ai_candidates_before_limit}")
        print(f"  Capped for scoring: {stats.ai_capped_count}")
        print(f"  Pending/skipped by cap: {stats.ai_skipped_by_cap}")
        print(f"  Historical persistence cohort: {len(persistent_jobs)}")
        if stats.ai_skipped_by_cap > 0:
            print(
                "  Note: Jobs skipped by cap are persisted with blank AI score "
                "for later scoring"
            )

    batch_size = stats.batch_size
    ai_candidate_count = stats.ai_candidate_count

    if ai_candidate_count > 0:
        total_batches = (ai_candidate_count + batch_size - 1) // batch_size
        ai_banner = "=" * 60
        if verbose:
            print(f"\n{ai_banner}")
            print("🤖 STARTING AI BATCH SCORING")
            print(f"{ai_banner}\n")
            print(f"📦 Total AI Candidate Jobs: {ai_candidate_count}")
            print(f"🧠 Total AI Scoring Batches: {total_batches}")
            print(f"📏 Batch Size: {batch_size}\n")

        candidate_profile = load_candidate_profile()
        if verbose:
            print(
                f"  Candidate profile: {paths.ai_candidate_profile_path()} "
                f"({len(candidate_profile)} chars)\n"
            )

        ai_t0 = time.monotonic()

        for batch_num, i in enumerate(
            range(0, ai_candidate_count, batch_size), start=1
        ):
            batch = ai_scoring_jobs[i : i + batch_size]
            batch_t0 = time.monotonic()
            batch_payload = batch_score_jobs(batch, candidate_profile)
            batch_sec = time.monotonic() - batch_t0

            if not batch_payload or not batch_payload.get("request_ok"):
                stats.batch_failures += 1
                if verbose:
                    print(f"⚠️ Batch {batch_num} failed (skipping, {batch_sec:.1f}s)")
                continue

            normalized_results = batch_payload.get("results") or []
            valid_results, skipped_invalid = validate_ai_batch_results(
                normalized_results, batch_size=len(batch)
            )

            stats.batches_processed += 1
            stats.ai_results_applied += len(valid_results)
            if verbose:
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

        stats.ai_total_sec = time.monotonic() - ai_t0
        if verbose:
            print(f"\n{ai_banner}")
            print("🤖 AI BATCH SCORING COMPLETE")
            print(f"{ai_banner}\n")
            print(f"✅ Total Batches Processed: {stats.batches_processed}")
            print(f"✅ Total Jobs AI Scored: {stats.ai_results_applied}")
            print(f"✅ Total Duration: {stats.ai_total_sec:.1f}s\n")

    return BatchScoringResult(
        ai_scoring_jobs=ai_scoring_jobs,
        pending_ai_jobs=pending_ai_jobs,
        persistent_jobs=persistent_jobs,
        stats=stats,
    )
