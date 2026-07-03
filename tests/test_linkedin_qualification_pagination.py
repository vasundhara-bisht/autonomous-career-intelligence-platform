"""Tests for qualification landing pagination (testid selectors + scoped fallback)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

_REPO_ROOT = Path(__file__).resolve().parent.parent
for entry in (str(_REPO_ROOT), str(_REPO_ROOT / "src")):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from scraper.linkedin import (  # noqa: E402
    _LinkedInTraversalContext,
    _LinkedInTraversalMetrics,
    _NEXT_PAGE_SCOPED_CANDIDATES,
    _QUALIFICATION_NEXT_PAGE_CANDIDATES,
    _li_find_page_level_control,
    _li_next_page_candidates,
    _li_probe_next_button_state,
    _li_try_next_page_transition,
)

_QUAL_URL = (
    "https://www.linkedin.com/jobs/search-results/"
    "?showHowYouFit=HOW_YOU_FIT&origin=QUALIFICATION_LANDING"
)
_CLASSIC_URL = "https://www.linkedin.com/jobs/search/?keywords=Product+Manager"
_SCOPED_MISS = {
    "linkedin_next_button_detected": False,
    "linkedin_next_button_disabled": None,
}
_PAGE_HIT = {
    "linkedin_next_button_detected": True,
    "linkedin_next_button_disabled": False,
}
_QUAL_VISIBLE_SEL = _QUALIFICATION_NEXT_PAGE_CANDIDATES[0][1]
_LEGACY_NEXT_SEL = _NEXT_PAGE_SCOPED_CANDIDATES[0][1]


class _FakeNextLoc:
    def __init__(
        self,
        *,
        count: int,
        visible: bool = True,
        disabled: object = None,
        aria_disabled: object = None,
    ) -> None:
        self._count = count
        self._visible = visible
        self._disabled = disabled
        self._aria_disabled = aria_disabled

    @property
    def first(self) -> "_FakeNextLoc":
        return self

    def count(self) -> int:
        return self._count

    def is_visible(self) -> bool:
        return self._visible

    def get_attribute(self, name: str) -> object:
        if name == "disabled":
            return self._disabled
        if name == "aria-disabled":
            return self._aria_disabled
        return None


class _FakeRoot:
    def __init__(self, responses: dict[str, _FakeNextLoc]) -> None:
        self._responses = responses

    def locator(self, sel: str) -> _FakeNextLoc:
        return self._responses.get(sel, _FakeNextLoc(count=0))


class NextPageCandidateListTests(unittest.TestCase):
    def test_classic_search_uses_legacy_selectors_only(self) -> None:
        labels = [label for label, _sel in _li_next_page_candidates(_CLASSIC_URL)]
        self.assertEqual(labels[:3], [c[0] for c in _NEXT_PAGE_SCOPED_CANDIDATES])
        self.assertNotIn("qual_pagination_next_visible", labels)

    def test_qual_landing_includes_testid_selectors(self) -> None:
        labels = [label for label, _sel in _li_next_page_candidates(_QUAL_URL)]
        self.assertEqual(labels[0], "qual_pagination_next_visible")
        self.assertIn("jobs_pagination_next", labels)


class NextPageProbeTests(unittest.TestCase):
    def test_legacy_pagination_probe_on_classic_url(self) -> None:
        root = _FakeRoot(
            {
                _LEGACY_NEXT_SEL: _FakeNextLoc(count=1, visible=True),
            }
        )
        state = _li_probe_next_button_state(
            root, candidates=_li_next_page_candidates(_CLASSIC_URL)
        )
        self.assertTrue(state["linkedin_next_button_detected"])
        self.assertFalse(state["linkedin_next_button_disabled"])

    def test_qual_testid_probe_detects_visible_next(self) -> None:
        root = _FakeRoot(
            {
                _QUAL_VISIBLE_SEL: _FakeNextLoc(count=1, visible=True),
            }
        )
        state = _li_probe_next_button_state(
            root, candidates=_li_next_page_candidates(_QUAL_URL)
        )
        self.assertTrue(state["linkedin_next_button_detected"])
        self.assertFalse(state["linkedin_next_button_disabled"])

    def test_qual_testid_probe_skips_hidden_next(self) -> None:
        root = _FakeRoot(
            {
                _QUAL_VISIBLE_SEL: _FakeNextLoc(count=0),
                _QUALIFICATION_NEXT_PAGE_CANDIDATES[1][1]: _FakeNextLoc(
                    count=1, visible=False
                ),
            }
        )
        state = _li_probe_next_button_state(
            root, candidates=_li_next_page_candidates(_QUAL_URL)
        )
        self.assertFalse(state["linkedin_next_button_detected"])

    def test_classic_candidates_ignore_qual_testid_only_dom(self) -> None:
        root = _FakeRoot(
            {
                _QUAL_VISIBLE_SEL: _FakeNextLoc(count=1, visible=True),
            }
        )
        state = _li_probe_next_button_state(
            root, candidates=_li_next_page_candidates(_CLASSIC_URL)
        )
        self.assertFalse(state["linkedin_next_button_detected"])


class QualificationPaginationFallbackTests(unittest.TestCase):
    def _run_transition(self, *, probe_side_effect: list[dict]) -> tuple[bool, MagicMock]:
        page = MagicMock()
        page.url = _QUAL_URL
        jobs_root = MagicMock()
        metrics = _LinkedInTraversalMetrics()
        trav_ctx = _LinkedInTraversalContext()
        scroll_loc = MagicMock()
        ctrl = MagicMock()

        patches = {
            "_li_probe_next_button_state": MagicMock(side_effect=probe_side_effect),
            "_li_find_page_level_control": MagicMock(
                return_value=(ctrl, "qual_pagination_next_visible")
            ),
            "_li_find_scoped_control": MagicMock(return_value=(None, None)),
            "_li_prepare_expansion_control_for_click": MagicMock(return_value=True),
            "_li_nudge_inner_scroll_if_far_from_bottom": MagicMock(),
            "_li_humanized_pause": MagicMock(),
            "_li_log_expansion_preclick_diagnostics": MagicMock(),
            "_li_count_job_cards": MagicMock(return_value=10),
            "_li_first_visible_job_card_signature": MagicMock(
                return_value={"job_id": "1", "title_text": "PM", "raw_card_text": ""}
            ),
            "_li_url_jobs_start_param": MagicMock(return_value="0"),
            "_li_wait_post_expansion_hydration": MagicMock(
                return_value={
                    "post_pagination_url": _QUAL_URL,
                    "first_sig_after": {"job_id": "2", "title_text": "PM2"},
                    "card_dom_refresh_detected": True,
                    "card_count_after_refresh": 15,
                }
            ),
            "_li_find_inner_jobs_scroll_locator": MagicMock(
                return_value=(scroll_loc, "inner_scroll")
            ),
            "_li_get_jobs_expansion_root": MagicMock(
                return_value=(jobs_root, "main:has(cards)")
            ),
            "_li_log_qualification_pagination_diagnostics": MagicMock(),
        }

        with patch.multiple("scraper.linkedin", **patches):
            ok, *_rest = _li_try_next_page_transition(
                page,
                jobs_root,
                scroll_loc,
                "inner_scroll",
                metrics,
                trav_ctx,
                jobs_root_desc="main:has(cards)",
            )
        return ok, ctrl

    def test_page_level_fallback_when_scoped_next_missing(self) -> None:
        ok, ctrl = self._run_transition(probe_side_effect=[_SCOPED_MISS, _PAGE_HIT])
        self.assertTrue(ok)
        ctrl.click.assert_called_once()

    def test_no_transition_when_both_scopes_miss_next(self) -> None:
        ok, ctrl = self._run_transition(probe_side_effect=[_SCOPED_MISS, _SCOPED_MISS])
        self.assertFalse(ok)
        ctrl.click.assert_not_called()

    def test_qual_testid_click_path_uses_qual_candidates(self) -> None:
        page = MagicMock()
        page.url = _QUAL_URL
        root = _FakeRoot(
            {
                _QUAL_VISIBLE_SEL: _FakeNextLoc(count=1, visible=True),
            }
        )

        with patch(
            "scraper.linkedin._li_expansion_element_passes_exclusion",
            return_value=True,
        ):
            ctrl, label = _li_find_page_level_control(
                root, _li_next_page_candidates(_QUAL_URL)
            )

        self.assertIsNotNone(ctrl)
        self.assertEqual(label, "qual_pagination_next_visible")


if __name__ == "__main__":
    unittest.main()
