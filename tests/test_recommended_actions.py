"""Tests for job-centric Recommended Actions (Phase 3A / 3A.2)."""

from __future__ import annotations

import ast
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DASHBOARD = _REPO_ROOT / "dashboard"
_SRC = _REPO_ROOT / "src"
for entry in (str(_REPO_ROOT), str(_DASHBOARD), str(_SRC)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from recommended_actions import compute_recommended_actions  # noqa: E402
from recommended_actions_config import (  # noqa: E402
    DISPLAY_CAP_APPLY_TODAY,
    DISPLAY_CAP_BY_QUEUE,
    DISPLAY_CAP_HIGH_CONFIDENCE,
    HIGH_CONFIDENCE_MIN,
    HIGH_SCORE_MIN,
    MAX_ROWS_PER_QUEUE,
    QUEUE_APPLY_THIS_WEEK,
    QUEUE_APPLY_TODAY,
    QUEUE_CARD_LAST_PX,
    QUEUE_CARD_WITH_DIVIDER_PX,
    QUEUE_HIGH_CONFIDENCE,
    QUEUE_NEEDS_REVIEW,
    QUEUE_PANEL_CHROME_TOP_PX,
    QUEUE_PANEL_HEIGHT_PX,
    QUEUE_PANEL_MIN_HEIGHT_PX,
    compute_queue_panel_height_px,
)


def _iso_days_ago(days: int, *, reference: date) -> str:
    return (reference - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")


def _job_row(
    *,
    key: str = "job-1",
    stage: str = "New",
    score: float = 8.0,
    ai_status: str = "scored",
    first_seen_days_ago: int = 2,
    currently_active: bool = True,
    reason: str = "Strong product fit",
    source: str = "instahyre",
    link: str = "https://example.com/jobs/1",
    reference: date,
) -> dict:
    return {
        "JOB_KEY": key,
        "JOB_KEY_V2": f"v2:{key}",
        "title": f"Title {key}",
        "company": f"Company {key}",
        "pipeline_stage": stage,
        "is_ai_scored": ai_status == "scored",
        "ai_status": ai_status,
        "score": score,
        "first_seen": _iso_days_ago(first_seen_days_ago, reference=reference),
        "currently_active": currently_active,
        "reason": reason,
        "source": source,
        "link": link,
    }


def _all_entity_keys(result) -> set[str]:
    keys: set[str] = set()
    for actions in (
        result.high_confidence,
        result.apply_today,
        result.apply_this_week,
        result.needs_review,
    ):
        keys.update(a.entity_key for a in actions)
    return keys


class RecommendedActionsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.reference = date(2026, 6, 10)

    def test_high_score_min_is_eight(self) -> None:
        self.assertEqual(HIGH_SCORE_MIN, 8)

    def test_high_confidence_min_is_nine(self) -> None:
        self.assertEqual(HIGH_CONFIDENCE_MIN, 9)

    def test_empty_cohort(self) -> None:
        result = compute_recommended_actions(
            pd.DataFrame(), reference_date=self.reference
        )
        self.assertEqual(result.high_confidence, [])
        self.assertEqual(result.apply_today, [])
        self.assertEqual(result.apply_this_week, [])
        self.assertEqual(result.needs_review, [])
        self.assertEqual(result.high_confidence_total, 0)
        self.assertEqual(result.apply_today_total, 0)
        self.assertEqual(result.apply_this_week_total, 0)
        self.assertEqual(result.needs_review_total, 0)

    def test_high_confidence_qualifies_recent_nine_plus(self) -> None:
        df = pd.DataFrame(
            [_job_row(key="fresh", score=9, first_seen_days_ago=2, reference=self.reference)]
        )
        result = compute_recommended_actions(df, reference_date=self.reference)
        self.assertEqual(result.high_confidence_total, 1)
        self.assertEqual(len(result.high_confidence), 1)
        action = result.high_confidence[0]
        self.assertEqual(action.queue, QUEUE_HIGH_CONFIDENCE)
        self.assertEqual(action.entity_key, "v2:fresh")
        self.assertIn("AI score 9/10", action.rationale)
        self.assertIn("high confidence", action.rationale)
        self.assertIn("Strong product fit", action.rationale)

    def test_apply_today_qualifies_score_eight_recent(self) -> None:
        df = pd.DataFrame(
            [_job_row(key="today", score=8, first_seen_days_ago=2, reference=self.reference)]
        )
        result = compute_recommended_actions(df, reference_date=self.reference)
        self.assertEqual(result.apply_today_total, 1)
        self.assertEqual(result.apply_today[0].queue, QUEUE_APPLY_TODAY)
        self.assertIn("discovered 2 days ago", result.apply_today[0].rationale)

    def test_apply_this_week_qualifies_days_eight_to_thirteen(self) -> None:
        df = pd.DataFrame(
            [
                _job_row(
                    key="week",
                    score=8,
                    first_seen_days_ago=9,
                    reference=self.reference,
                )
            ]
        )
        result = compute_recommended_actions(df, reference_date=self.reference)
        self.assertEqual(result.apply_this_week_total, 1)
        self.assertEqual(result.apply_this_week[0].queue, QUEUE_APPLY_THIS_WEEK)
        self.assertIn("in list 9 days", result.apply_this_week[0].rationale)

    def test_score_nine_not_in_apply_today_or_week(self) -> None:
        df = pd.DataFrame(
            [
                _job_row(
                    key="nine-today",
                    score=9,
                    first_seen_days_ago=2,
                    reference=self.reference,
                ),
                _job_row(
                    key="nine-week",
                    score=9,
                    first_seen_days_ago=9,
                    reference=self.reference,
                ),
            ]
        )
        result = compute_recommended_actions(df, reference_date=self.reference)
        self.assertEqual(result.apply_today_total, 0)
        self.assertEqual(result.apply_this_week_total, 0)
        self.assertEqual(result.high_confidence_total, 2)

    def test_stale_nine_plus_goes_to_needs_review_not_high_confidence(self) -> None:
        df = pd.DataFrame(
            [
                _job_row(
                    key="stale-nine",
                    score=9,
                    first_seen_days_ago=20,
                    reference=self.reference,
                )
            ]
        )
        result = compute_recommended_actions(df, reference_date=self.reference)
        self.assertEqual(result.high_confidence_total, 0)
        self.assertEqual(result.needs_review_total, 1)
        self.assertEqual(result.needs_review[0].entity_key, "v2:stale-nine")

    def test_apply_today_excludes_days_beyond_three(self) -> None:
        df = pd.DataFrame(
            [
                _job_row(
                    key="old",
                    score=8,
                    first_seen_days_ago=5,
                    reference=self.reference,
                )
            ]
        )
        result = compute_recommended_actions(df, reference_date=self.reference)
        self.assertEqual(result.apply_today_total, 0)
        self.assertEqual(result.apply_this_week_total, 1)

    def test_apply_today_excludes_user_managed(self) -> None:
        df = pd.DataFrame(
            [
                _job_row(
                    key="applied",
                    stage="Applied",
                    score=9,
                    first_seen_days_ago=2,
                    reference=self.reference,
                )
            ]
        )
        result = compute_recommended_actions(df, reference_date=self.reference)
        self.assertEqual(_all_entity_keys(result), set())

    def test_apply_queues_require_scored_status(self) -> None:
        for status in ("pending", "skipped_by_cap"):
            with self.subTest(status=status):
                df = pd.DataFrame(
                    [
                        _job_row(
                            key=status,
                            score=9,
                            ai_status=status,
                            first_seen_days_ago=2,
                            reference=self.reference,
                        )
                    ]
                )
                result = compute_recommended_actions(df, reference_date=self.reference)
                self.assertEqual(result.high_confidence_total, 0)

    def test_apply_queues_exclude_inactive(self) -> None:
        df = pd.DataFrame(
            [
                _job_row(
                    key="inactive",
                    score=9,
                    currently_active=False,
                    first_seen_days_ago=2,
                    reference=self.reference,
                )
            ]
        )
        result = compute_recommended_actions(df, reference_date=self.reference)
        self.assertEqual(result.high_confidence_total, 0)
        self.assertEqual(result.apply_today_total, 0)
        self.assertEqual(result.apply_this_week_total, 0)

    def test_apply_queues_exclude_empty_reason(self) -> None:
        df = pd.DataFrame(
            [
                _job_row(
                    key="no-reason",
                    score=9,
                    reason="",
                    first_seen_days_ago=2,
                    reference=self.reference,
                )
            ]
        )
        result = compute_recommended_actions(df, reference_date=self.reference)
        self.assertEqual(result.high_confidence_total, 0)

    def test_needs_review_qualifies_old_high_score_without_active(self) -> None:
        df = pd.DataFrame(
            [
                _job_row(
                    key="stale",
                    stage="Saved",
                    score=8,
                    first_seen_days_ago=20,
                    currently_active=False,
                    reason="",
                    reference=self.reference,
                )
            ]
        )
        result = compute_recommended_actions(df, reference_date=self.reference)
        self.assertEqual(result.needs_review_total, 1)
        action = result.needs_review[0]
        self.assertEqual(action.queue, QUEUE_NEEDS_REVIEW)
        self.assertIn("in Saved for 20 days", action.rationale)
        self.assertIn("not yet applied", action.rationale)

    def test_waterfall_all_four_queues_mutually_exclusive(self) -> None:
        df = pd.DataFrame(
            [
                _job_row(
                    key="hc",
                    score=10,
                    first_seen_days_ago=2,
                    reference=self.reference,
                ),
                _job_row(
                    key="today",
                    score=8,
                    first_seen_days_ago=2,
                    reference=self.reference,
                ),
                _job_row(
                    key="week",
                    score=8,
                    first_seen_days_ago=9,
                    reference=self.reference,
                ),
                _job_row(
                    key="review",
                    score=8,
                    first_seen_days_ago=21,
                    reference=self.reference,
                ),
            ]
        )
        result = compute_recommended_actions(df, reference_date=self.reference)
        hc_keys = {a.entity_key for a in result.high_confidence}
        today_keys = {a.entity_key for a in result.apply_today}
        week_keys = {a.entity_key for a in result.apply_this_week}
        review_keys = {a.entity_key for a in result.needs_review}
        self.assertEqual(hc_keys, {"v2:hc"})
        self.assertEqual(today_keys, {"v2:today"})
        self.assertEqual(week_keys, {"v2:week"})
        self.assertEqual(review_keys, {"v2:review"})
        all_keys = hc_keys | today_keys | week_keys | review_keys
        self.assertEqual(len(all_keys), 4)

    def test_ranking_high_confidence(self) -> None:
        df = pd.DataFrame(
            [
                _job_row(
                    key="lower",
                    score=9,
                    first_seen_days_ago=1,
                    reference=self.reference,
                ),
                _job_row(
                    key="higher",
                    score=10,
                    first_seen_days_ago=5,
                    reference=self.reference,
                ),
            ]
        )
        result = compute_recommended_actions(df, reference_date=self.reference)
        self.assertEqual(result.high_confidence[0].entity_key, "v2:higher")
        self.assertEqual(result.high_confidence[1].entity_key, "v2:lower")

    def test_ranking_apply_today(self) -> None:
        df = pd.DataFrame(
            [
                _job_row(
                    key="lower",
                    score=8,
                    first_seen_days_ago=1,
                    reference=self.reference,
                ),
                _job_row(
                    key="higher",
                    score=8.5,
                    first_seen_days_ago=3,
                    reference=self.reference,
                ),
            ]
        )
        result = compute_recommended_actions(df, reference_date=self.reference)
        self.assertEqual(result.apply_today[0].entity_key, "v2:higher")
        self.assertEqual(result.apply_today[1].entity_key, "v2:lower")

    def test_ranking_apply_this_week_oldest_first(self) -> None:
        df = pd.DataFrame(
            [
                _job_row(
                    key="newer",
                    score=8,
                    first_seen_days_ago=5,
                    reference=self.reference,
                ),
                _job_row(
                    key="older",
                    score=8,
                    first_seen_days_ago=12,
                    reference=self.reference,
                ),
            ]
        )
        result = compute_recommended_actions(df, reference_date=self.reference)
        self.assertEqual(result.apply_this_week[0].entity_key, "v2:older")
        self.assertEqual(result.apply_this_week[1].entity_key, "v2:newer")

    def test_ranking_needs_review(self) -> None:
        df = pd.DataFrame(
            [
                _job_row(
                    key="less-stale",
                    score=8,
                    first_seen_days_ago=14,
                    reference=self.reference,
                ),
                _job_row(
                    key="more-stale",
                    score=8,
                    first_seen_days_ago=30,
                    reference=self.reference,
                ),
            ]
        )
        result = compute_recommended_actions(df, reference_date=self.reference)
        self.assertEqual(result.needs_review[0].entity_key, "v2:more-stale")

    def test_max_rows_cap_per_queue(self) -> None:
        rows = [
            _job_row(
                key=f"job-{i}",
                score=8,
                first_seen_days_ago=2,
                reference=self.reference,
            )
            for i in range(MAX_ROWS_PER_QUEUE + 3)
        ]
        result = compute_recommended_actions(
            pd.DataFrame(rows), reference_date=self.reference
        )
        self.assertEqual(len(result.apply_today), MAX_ROWS_PER_QUEUE)
        self.assertEqual(result.apply_today_total, MAX_ROWS_PER_QUEUE + 3)
        self.assertEqual(result.apply_today_overflow, 3)

    def test_display_caps_defined_for_all_queues(self) -> None:
        self.assertEqual(DISPLAY_CAP_HIGH_CONFIDENCE, 8)
        self.assertEqual(DISPLAY_CAP_APPLY_TODAY, 10)
        self.assertEqual(len(DISPLAY_CAP_BY_QUEUE), 4)

    def test_source_and_job_url_populated(self) -> None:
        df = pd.DataFrame(
            [
                _job_row(
                    key="linked",
                    score=9,
                    source="linkedin",
                    link="https://www.linkedin.com/jobs/view/123",
                    first_seen_days_ago=2,
                    reference=self.reference,
                )
            ]
        )
        result = compute_recommended_actions(df, reference_date=self.reference)
        action = result.high_confidence[0]
        self.assertEqual(action.source, "linkedin")
        self.assertEqual(action.job_url, "https://www.linkedin.com/jobs/view/123")

    def test_full_rationale_populated(self) -> None:
        df = pd.DataFrame(
            [
                _job_row(
                    key="fresh",
                    score=9,
                    reason="Complete AI reason text for the role",
                    first_seen_days_ago=2,
                    reference=self.reference,
                )
            ]
        )
        result = compute_recommended_actions(df, reference_date=self.reference)
        action = result.high_confidence[0]
        self.assertIn("Complete AI reason text", action.full_rationale)
        self.assertGreater(len(action.full_rationale), len(action.rationale))

    def test_max_rows_none_returns_all(self) -> None:
        rows = [
            _job_row(
                key=f"job-{i}",
                score=8,
                first_seen_days_ago=2,
                reference=self.reference,
            )
            for i in range(MAX_ROWS_PER_QUEUE + 2)
        ]
        result = compute_recommended_actions(
            pd.DataFrame(rows),
            reference_date=self.reference,
            max_rows_per_queue=None,
        )
        self.assertEqual(len(result.apply_today), MAX_ROWS_PER_QUEUE + 2)
        self.assertEqual(result.apply_today_total, MAX_ROWS_PER_QUEUE + 2)

    def test_score_below_threshold_excluded(self) -> None:
        df = pd.DataFrame(
            [
                _job_row(
                    key="borderline",
                    score=7.9,
                    first_seen_days_ago=2,
                    reference=self.reference,
                )
            ]
        )
        result = compute_recommended_actions(df, reference_date=self.reference)
        self.assertEqual(_all_entity_keys(result), set())

    def test_nine_plus_inactive_excluded_entirely(self) -> None:
        df = pd.DataFrame(
            [
                _job_row(
                    key="inactive-nine",
                    score=9,
                    currently_active=False,
                    first_seen_days_ago=5,
                    reference=self.reference,
                )
            ]
        )
        result = compute_recommended_actions(df, reference_date=self.reference)
        self.assertEqual(_all_entity_keys(result), set())

    def test_no_recruiter_imports(self) -> None:
        engine_path = _DASHBOARD / "recommended_actions.py"
        config_path = _DASHBOARD / "recommended_actions_config.py"
        ui_path = _DASHBOARD / "recommended_actions_ui.py"
        forbidden = (
            "recruiter",
            "crm",
            "recruiter_stage",
            "recruiter_replied",
        )
        for path in (engine_path, config_path, ui_path):
            source = path.read_text(encoding="utf-8").lower()
            tree = ast.parse(path.read_text(encoding="utf-8"))
            imports = ast.walk(tree)
            import_names = []
            for node in imports:
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        import_names.append(alias.name.lower())
                elif isinstance(node, ast.ImportFrom) and node.module:
                    import_names.append(node.module.lower())
            for name in import_names:
                self.assertNotIn("recruiter", name, msg=f"{path.name} imports {name}")
            for token in forbidden:
                if token in {"recruiter", "crm"}:
                    self.assertNotIn(
                        f"from recruiter",
                        source,
                        msg=f"{path.name} must not import recruiter modules",
                    )


class QueuePanelHeightTests(unittest.TestCase):
    def test_empty_queue_uses_min_height(self) -> None:
        self.assertEqual(
            compute_queue_panel_height_px(visible_card_count=0, has_cards=False),
            QUEUE_PANEL_MIN_HEIGHT_PX,
        )

    def test_single_card_height(self) -> None:
        self.assertEqual(
            compute_queue_panel_height_px(visible_card_count=1, has_cards=True),
            QUEUE_PANEL_CHROME_TOP_PX + QUEUE_CARD_LAST_PX,
        )

    def test_three_cards_fits_measured_content(self) -> None:
        expected = (
            QUEUE_PANEL_CHROME_TOP_PX
            + 2 * QUEUE_CARD_WITH_DIVIDER_PX
            + QUEUE_CARD_LAST_PX
        )
        self.assertEqual(
            compute_queue_panel_height_px(visible_card_count=3, has_cards=True),
            min(QUEUE_PANEL_HEIGHT_PX, expected),
        )

    def test_many_cards_cap_at_max(self) -> None:
        self.assertEqual(
            compute_queue_panel_height_px(visible_card_count=8, has_cards=True),
            QUEUE_PANEL_HEIGHT_PX,
        )


if __name__ == "__main__":
    unittest.main()
