"""Job-centric Recommended Actions engine (Phase 3A / 3A.2 — dashboard_df only)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd

from agent.pipeline_stages import is_discovery_pipeline_stage
from listing_visibility import is_listing_open_for_recommended_actions
from recommended_actions_config import (
    APPLY_TODAY_MAX_DAYS,
    APPLY_WEEK_MAX_DAYS,
    APPLY_WEEK_MIN_DAYS,
    HIGH_CONFIDENCE_MIN,
    HIGH_SCORE_MIN,
    MAX_ROWS_PER_QUEUE,
    NEEDS_REVIEW_MIN_DAYS,
    QUEUE_APPLY_THIS_WEEK,
    QUEUE_APPLY_TODAY,
    QUEUE_HIGH_CONFIDENCE,
    QUEUE_NEEDS_REVIEW,
    REASON_SNIPPET_MAX_LEN,
)


@dataclass(frozen=True)
class RecommendedAction:
    queue: str
    entity_key: str
    title: str
    company: str
    score: float
    rationale: str
    full_rationale: str
    source: str = ""
    job_url: str = ""
    job_key: str = ""
    job_key_v2: str = ""


@dataclass(frozen=True)
class RecommendedActionsResult:
    high_confidence: list[RecommendedAction]
    apply_today: list[RecommendedAction]
    apply_this_week: list[RecommendedAction]
    needs_review: list[RecommendedAction]
    high_confidence_total: int
    apply_today_total: int
    apply_this_week_total: int
    needs_review_total: int

    @property
    def high_confidence_overflow(self) -> int:
        return max(0, self.high_confidence_total - len(self.high_confidence))

    @property
    def apply_today_overflow(self) -> int:
        return max(0, self.apply_today_total - len(self.apply_today))

    @property
    def apply_this_week_overflow(self) -> int:
        return max(0, self.apply_this_week_total - len(self.apply_this_week))

    @property
    def needs_review_overflow(self) -> int:
        return max(0, self.needs_review_total - len(self.needs_review))


def _reference_day(reference_date: date | None) -> date:
    return reference_date or date.today()


def _parse_first_seen(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, errors="coerce")


def _days_ago(first_seen: pd.Timestamp | None, *, reference: date) -> int | None:
    if first_seen is None or pd.isna(first_seen):
        return None
    seen_date = first_seen.date() if hasattr(first_seen, "date") else None
    if seen_date is None:
        return None
    return (reference - seen_date).days


def _coerce_bool(value: object) -> bool:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return bool(int(value))
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "on"}:
        return True
    return False


def _entity_key(row: pd.Series) -> str:
    v2 = str(row.get("JOB_KEY_V2", "") or "").strip()
    if v2:
        return v2
    return str(row.get("JOB_KEY", "") or "").strip()


def _normalize_stage(row: pd.Series) -> str:
    stage = row.get("pipeline_stage", row.get("Status", "New"))
    if stage is None or (isinstance(stage, float) and pd.isna(stage)):
        return "New"
    text = str(stage).strip()
    return text if text else "New"


def _score_value(row: pd.Series) -> float:
    if "score" in row.index and pd.notna(row.get("score")):
        return float(row["score"])
    if "ai_score" in row.index and pd.notna(row.get("ai_score")):
        return float(row["ai_score"])
    return 0.0


def _is_high_scored_row(row: pd.Series) -> bool:
    if "is_ai_scored" in row.index:
        if not _coerce_bool(row.get("is_ai_scored")):
            return False
    status = str(row.get("ai_status", "") or "").strip().lower()
    if status and status != "scored":
        return False
    return _score_value(row) >= HIGH_SCORE_MIN


def _reason_snippet(reason: object) -> str:
    text = str(reason or "").strip()
    if len(text) <= REASON_SNIPPET_MAX_LEN:
        return text
    return text[: REASON_SNIPPET_MAX_LEN - 1].rstrip() + "…"


def _discovery_mask(df: pd.DataFrame) -> pd.Series:
    stages = df.apply(_normalize_stage, axis=1)
    return stages.map(is_discovery_pipeline_stage)


def _prepare_working_frame(
    dashboard_df: pd.DataFrame, *, reference: date
) -> pd.DataFrame:
    if dashboard_df.empty:
        return dashboard_df.copy()

    work = dashboard_df.copy()
    work["_stage"] = work.apply(_normalize_stage, axis=1)
    work["_score"] = work.apply(_score_value, axis=1)
    work["_entity_key"] = work.apply(_entity_key, axis=1)
    work["_first_seen"] = _parse_first_seen(
        work["first_seen"] if "first_seen" in work.columns else pd.Series(dtype=object)
    )
    if "age_days_derived" in work.columns:
        work["_days_ago"] = work["age_days_derived"]
    else:
        work["_days_ago"] = work["_first_seen"].apply(
            lambda ts: _days_ago(ts, reference=reference)
        )
    if "listing_status" in work.columns:
        work["_active"] = work.apply(is_listing_open_for_recommended_actions, axis=1)
    else:
        work["_active"] = False
    if "reason" in work.columns:
        work["_reason"] = work["reason"].fillna("").astype(str).str.strip()
    else:
        work["_reason"] = ""
    work["_high_scored"] = work.apply(_is_high_scored_row, axis=1)
    return work


def _assign_queue(row: pd.Series) -> str | None:
    days = row["_days_ago"]
    if days is None or pd.isna(days):
        return None

    if days >= NEEDS_REVIEW_MIN_DAYS:
        return QUEUE_NEEDS_REVIEW

    score = float(row["_score"])
    active = bool(row["_active"])
    has_reason = bool(str(row["_reason"]).strip())

    if (
        score >= HIGH_CONFIDENCE_MIN
        and active
        and has_reason
        and days <= APPLY_WEEK_MAX_DAYS
    ):
        return QUEUE_HIGH_CONFIDENCE

    if HIGH_SCORE_MIN <= score < HIGH_CONFIDENCE_MIN and active and has_reason:
        if days <= APPLY_TODAY_MAX_DAYS:
            return QUEUE_APPLY_TODAY
        if APPLY_WEEK_MIN_DAYS <= days <= APPLY_WEEK_MAX_DAYS:
            return QUEUE_APPLY_THIS_WEEK

    return None


def _base_action_fields(row: pd.Series) -> dict[str, str | float]:
    return {
        "entity_key": str(row["_entity_key"]),
        "title": str(row.get("title", "") or "Unknown"),
        "company": str(row.get("company", "") or "Unknown"),
        "score": float(row["_score"]),
        "source": str(row.get("source", "") or "").strip(),
        "job_url": str(row.get("link", "") or "").strip(),
        "job_key": str(row.get("JOB_KEY", "") or "").strip(),
        "job_key_v2": str(row.get("JOB_KEY_V2", "") or "").strip(),
    }


def _build_high_confidence_action(row: pd.Series) -> RecommendedAction:
    days = row["_days_ago"]
    days_label = days if days is not None else "?"
    score = float(row["_score"])
    reason = str(row["_reason"] or "").strip()
    snippet = _reason_snippet(reason)
    rationale = f"AI score {score:g}/10 · high confidence · discovered {days_label} days ago"
    if snippet:
        rationale = f"{rationale} · {snippet}"
    lines = [
        f"AI score {score:g}/10",
        "High confidence match",
        f"Discovered {days_label} days ago",
        "Stage: discovery (New or Saved)",
    ]
    if reason:
        lines.append(f"AI reason: {reason}")
    return RecommendedAction(
        queue=QUEUE_HIGH_CONFIDENCE,
        rationale=rationale,
        full_rationale="\n".join(lines),
        **_base_action_fields(row),
    )


def _build_apply_today_action(row: pd.Series) -> RecommendedAction:
    days = row["_days_ago"]
    days_label = days if days is not None else "?"
    score = float(row["_score"])
    reason = str(row["_reason"] or "").strip()
    snippet = _reason_snippet(reason)
    rationale = f"AI score {score:g}/10 · discovered {days_label} days ago"
    if snippet:
        rationale = f"{rationale} · {snippet}"
    lines = [
        f"AI score {score:g}/10",
        f"Discovered {days_label} days ago",
        "Stage: discovery (New or Saved)",
    ]
    if reason:
        lines.append(f"AI reason: {reason}")
    return RecommendedAction(
        queue=QUEUE_APPLY_TODAY,
        rationale=rationale,
        full_rationale="\n".join(lines),
        **_base_action_fields(row),
    )


def _build_apply_this_week_action(row: pd.Series) -> RecommendedAction:
    days = row["_days_ago"]
    days_label = days if days is not None else "?"
    score = float(row["_score"])
    reason = str(row["_reason"] or "").strip()
    snippet = _reason_snippet(reason)
    rationale = f"AI score {score:g}/10 · in list {days_label} days · apply this week"
    if snippet:
        rationale = f"{rationale} · {snippet}"
    lines = [
        f"AI score {score:g}/10",
        f"In discovery list for {days_label} days",
        "Apply this week",
        "Stage: discovery (New or Saved)",
    ]
    if reason:
        lines.append(f"AI reason: {reason}")
    return RecommendedAction(
        queue=QUEUE_APPLY_THIS_WEEK,
        rationale=rationale,
        full_rationale="\n".join(lines),
        **_base_action_fields(row),
    )


def _build_needs_review_action(row: pd.Series) -> RecommendedAction:
    days = row["_days_ago"]
    days_label = days if days is not None else "?"
    score = float(row["_score"])
    stage = str(row["_stage"])
    reason = str(row["_reason"] or "").strip()
    rationale = (
        f"AI score {score:g}/10 · in {stage} for {days_label} days · not yet applied"
    )
    lines = [
        f"AI score {score:g}/10",
        f"In {stage} for {days_label} days",
        "Not yet applied",
    ]
    if reason:
        lines.append(f"AI reason: {reason}")
    return RecommendedAction(
        queue=QUEUE_NEEDS_REVIEW,
        rationale=rationale,
        full_rationale="\n".join(lines),
        **_base_action_fields(row),
    )


_QUEUE_BUILDERS = {
    QUEUE_HIGH_CONFIDENCE: _build_high_confidence_action,
    QUEUE_APPLY_TODAY: _build_apply_today_action,
    QUEUE_APPLY_THIS_WEEK: _build_apply_this_week_action,
    QUEUE_NEEDS_REVIEW: _build_needs_review_action,
}


def _sort_high_confidence(df: pd.DataFrame) -> pd.DataFrame:
    return df.sort_values(
        by=["_score", "_first_seen"],
        ascending=[False, False],
        kind="mergesort",
    )


def _sort_apply_today(df: pd.DataFrame) -> pd.DataFrame:
    return df.sort_values(
        by=["_score", "_first_seen"],
        ascending=[False, False],
        kind="mergesort",
    )


def _sort_apply_this_week(df: pd.DataFrame) -> pd.DataFrame:
    return df.sort_values(
        by=["_score", "_first_seen"],
        ascending=[False, True],
        kind="mergesort",
    )


def _sort_needs_review(df: pd.DataFrame) -> pd.DataFrame:
    return df.sort_values(
        by=["_score", "_days_ago"],
        ascending=[False, False],
        kind="mergesort",
    )


_QUEUE_SORTERS = {
    QUEUE_HIGH_CONFIDENCE: _sort_high_confidence,
    QUEUE_APPLY_TODAY: _sort_apply_today,
    QUEUE_APPLY_THIS_WEEK: _sort_apply_this_week,
    QUEUE_NEEDS_REVIEW: _sort_needs_review,
}


def _cap_actions(
    df: pd.DataFrame,
    *,
    builder,
    sorter,
    max_rows: int | None,
) -> tuple[list[RecommendedAction], int]:
    if df.empty:
        return [], 0
    ordered = sorter(df)
    total = len(ordered)
    if max_rows is None:
        capped = ordered
    else:
        capped = ordered.head(max_rows)
    actions = [builder(row) for _, row in capped.iterrows()]
    return actions, total


def _empty_result() -> RecommendedActionsResult:
    return RecommendedActionsResult([], [], [], [], 0, 0, 0, 0)


def compute_recommended_actions(
    dashboard_df: pd.DataFrame,
    *,
    reference_date: date | None = None,
    max_rows_per_queue: int | None = MAX_ROWS_PER_QUEUE,
) -> RecommendedActionsResult:
    """Build four mutually exclusive Recommended Actions queues from dashboard_df."""
    reference = _reference_day(reference_date)
    if dashboard_df.empty:
        return _empty_result()

    work = _prepare_working_frame(dashboard_df, reference=reference)
    discovery = _discovery_mask(work)
    high_scored = work["_high_scored"]
    eligible = work.loc[discovery & high_scored].copy()
    if eligible.empty:
        return _empty_result()

    eligible["_queue"] = eligible.apply(_assign_queue, axis=1)
    eligible = eligible.loc[eligible["_queue"].notna()]

    results: dict[str, tuple[list[RecommendedAction], int]] = {}
    for queue_id in (
        QUEUE_HIGH_CONFIDENCE,
        QUEUE_APPLY_TODAY,
        QUEUE_APPLY_THIS_WEEK,
        QUEUE_NEEDS_REVIEW,
    ):
        queue_df = eligible.loc[eligible["_queue"] == queue_id]
        results[queue_id] = _cap_actions(
            queue_df,
            builder=_QUEUE_BUILDERS[queue_id],
            sorter=_QUEUE_SORTERS[queue_id],
            max_rows=max_rows_per_queue,
        )

    hc_actions, hc_total = results[QUEUE_HIGH_CONFIDENCE]
    today_actions, today_total = results[QUEUE_APPLY_TODAY]
    week_actions, week_total = results[QUEUE_APPLY_THIS_WEEK]
    review_actions, review_total = results[QUEUE_NEEDS_REVIEW]

    return RecommendedActionsResult(
        high_confidence=hc_actions,
        apply_today=today_actions,
        apply_this_week=week_actions,
        needs_review=review_actions,
        high_confidence_total=hc_total,
        apply_today_total=today_total,
        apply_this_week_total=week_total,
        needs_review_total=review_total,
    )
