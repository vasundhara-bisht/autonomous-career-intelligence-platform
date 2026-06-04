from __future__ import annotations

import os
from collections import defaultdict
from typing import Any


def debug_stage1_enabled() -> bool:
    return os.environ.get("DEBUG_STAGE1", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def log_job_start(job):
    source = job.get("source", "unknown").upper()

    print("\n==============================")
    print(f"🆕 [{source}] {job.get('title')} @ {job.get('company')}")
    print("==============================")


def log_check(score):
    print(f" 🔍 Score: {score}")


def log_rejected(score):
    print(f" ❌ Rejected")


def log_accepted():
    print(" ✅ Accepted")


def log_duplicate(title_score=None, company_score=None):
    if title_score is not None:
        print(f"   🔁 Duplicate (title: {title_score}, company: {company_score})")
    else:
        print("   🔁 Duplicate (exact link)")


def log_fetching():
    print("   📄 Fetching description...")


def log_fetched():
    print("   ✅ Description fetched")


# =========================
# 🔥 SECTION DIVIDER LOGS
# =========================
def log_section(title):
    line = "=" * 60
    print(f"\n{line}")
    print(f"   {title}")
    print(f"{line}\n")


_SCORE_BUCKET_ORDER = ("<=0", "1-3", "4-6", "7-9", "10+")


def _score_bucket(score: int) -> str:
    if score <= 0:
        return "<=0"
    if score <= 3:
        return "1-3"
    if score <= 6:
        return "4-6"
    if score <= 9:
        return "7-9"
    return "10+"


def _normalize_source(job: dict) -> str:
    return str(job.get("source", "unknown") or "unknown").strip().lower() or "unknown"


class Stage1Aggregator:
    """Collect Stage-1 outcomes for a single pipeline run (logging only)."""

    def __init__(self) -> None:
        self.total = 0
        self.accepted = 0
        self.rejected = 0
        self.score_buckets: dict[str, int] = {k: 0 for k in _SCORE_BUCKET_ORDER}
        self.accepted_by_source: dict[str, int] = defaultdict(int)
        self.rejected_by_source: dict[str, int] = defaultdict(int)
        self._borderline_accepted: list[dict[str, Any]] = []
        self._high_confidence_accepted: list[dict[str, Any]] = []

    def record(self, job: dict, score: int, *, accepted: bool) -> None:
        self.total += 1
        self.score_buckets[_score_bucket(int(score))] += 1
        source = _normalize_source(job)

        if accepted:
            self.accepted += 1
            self.accepted_by_source[source] += 1
            if 4 <= score <= 5:
                self._borderline_accepted.append(job)
            if score >= 10:
                self._high_confidence_accepted.append(job)
        else:
            self.rejected += 1
            self.rejected_by_source[source] += 1

    def print_summary(self, *, list_limit: int = 12) -> None:
        print("\n🚦 STAGE 1 SUMMARY\n")
        print(f"Total evaluated: {self.total}")
        print(f"Accepted: {self.accepted}")
        print(f"Rejected: {self.rejected}\n")

        print("Score distribution:")
        for bucket in _SCORE_BUCKET_ORDER:
            print(f"{bucket:4} : {self.score_buckets[bucket]}")
        print()

        print("Accepted by source:")
        if self.accepted_by_source:
            for source in sorted(self.accepted_by_source):
                print(f"{source}: {self.accepted_by_source[source]}")
        else:
            print("(none)")
        print()

        print("Rejected by source:")
        if self.rejected_by_source:
            for source in sorted(self.rejected_by_source):
                print(f"{source}: {self.rejected_by_source[source]}")
        else:
            print("(none)")

        if self._borderline_accepted:
            print("\nBorderline accepted:")
            print("- scores 4-5 only")
            for job in self._borderline_accepted[:list_limit]:
                src = _normalize_source(job)
                sc = job.get("score", "?")
                print(f"  • [{src}] {job.get('title')} @ {job.get('company')} (score {sc})")
            extra = len(self._borderline_accepted) - list_limit
            if extra > 0:
                print(f"  … and {extra} more")

        if self._high_confidence_accepted:
            print("\nHigh-confidence accepted:")
            print("- scores >=10 only")
            for job in self._high_confidence_accepted[:list_limit]:
                src = _normalize_source(job)
                sc = job.get("score", "?")
                print(f"  • [{src}] {job.get('title')} @ {job.get('company')} (score {sc})")
            extra = len(self._high_confidence_accepted) - list_limit
            if extra > 0:
                print(f"  … and {extra} more")

        print()
