"""Thresholds and constants for job-centric Recommended Actions (Phase 3A / 3A.2)."""

from __future__ import annotations

from agent.pipeline_stages import DISCOVERY_PIPELINE_STAGES

HIGH_SCORE_MIN = 8
HIGH_CONFIDENCE_MIN = 9
APPLY_TODAY_MAX_DAYS = 3
APPLY_WEEK_MIN_DAYS = 4
APPLY_WEEK_MAX_DAYS = 13
NEEDS_REVIEW_MIN_DAYS = 14
MAX_ROWS_PER_QUEUE = 5
REASON_SNIPPET_MAX_LEN = 80

DISPLAY_CAP_HIGH_CONFIDENCE = 8
DISPLAY_CAP_APPLY_TODAY = 10
DISPLAY_CAP_APPLY_WEEK = 12
DISPLAY_CAP_NEEDS_REVIEW = 10

DISCOVERY_STAGES = DISCOVERY_PIPELINE_STAGES

QUEUE_HIGH_CONFIDENCE = "high_confidence"
QUEUE_APPLY_TODAY = "apply_today"
QUEUE_APPLY_THIS_WEEK = "apply_this_week"
QUEUE_NEEDS_REVIEW = "needs_review"

HIGH_CONFIDENCE_LABEL = "High Confidence"
APPLY_TODAY_LABEL = "Apply Today"
APPLY_THIS_WEEK_LABEL = "Apply This Week"
NEEDS_REVIEW_LABEL = "Needs Review"
NEEDS_REVIEW_SUBTITLE = "14+ days old • Decide or clear"

RECOMMENDED_ACTIONS_TITLE = "Recommended Actions"

QUEUE_PANEL_HEIGHT_PX = 360
QUEUE_PANEL_MIN_HEIGHT_PX = 72
# Measured from live Streamlit DOM (title → next title / action row).
QUEUE_PANEL_CHROME_TOP_PX = 16
QUEUE_CARD_WITH_DIVIDER_PX = 131
QUEUE_CARD_LAST_PX = 99
QUEUE_LOAD_MORE_INCREMENT = 25


def compute_queue_panel_height_px(
    *,
    visible_card_count: int,
    has_cards: bool,
) -> int:
    """Fit bordered panel to visible cards; cap at QUEUE_PANEL_HEIGHT_PX for scroll."""
    if not has_cards or visible_card_count <= 0:
        return QUEUE_PANEL_MIN_HEIGHT_PX
    if visible_card_count == 1:
        cards_height = QUEUE_CARD_LAST_PX
    else:
        cards_height = (
            QUEUE_CARD_WITH_DIVIDER_PX * (visible_card_count - 1) + QUEUE_CARD_LAST_PX
        )
    return min(QUEUE_PANEL_HEIGHT_PX, QUEUE_PANEL_CHROME_TOP_PX + cards_height)

DISPLAY_CAP_BY_QUEUE: dict[str, int] = {
    QUEUE_HIGH_CONFIDENCE: DISPLAY_CAP_HIGH_CONFIDENCE,
    QUEUE_APPLY_TODAY: DISPLAY_CAP_APPLY_TODAY,
    QUEUE_APPLY_THIS_WEEK: DISPLAY_CAP_APPLY_WEEK,
    QUEUE_NEEDS_REVIEW: DISPLAY_CAP_NEEDS_REVIEW,
}

APPLY_ACTION_QUEUES = frozenset(
    {QUEUE_HIGH_CONFIDENCE, QUEUE_APPLY_TODAY, QUEUE_APPLY_THIS_WEEK}
)
