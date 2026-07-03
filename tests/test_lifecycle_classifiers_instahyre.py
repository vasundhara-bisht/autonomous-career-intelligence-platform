"""Unit tests for Instahyre lifecycle classifier (T1B / TD7 §4.5)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
for entry in (str(_REPO_ROOT), str(_SRC)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

_FIXTURES = Path(__file__).resolve().parent / "fixtures"
_VALID_URL = "https://www.instahyre.com/job-418799-backend-engineer/"


def _load_fixture(name: str) -> str:
    return (_FIXTURES / name).read_text(encoding="utf-8")


class InstahyreUrlValidationTests(unittest.TestCase):
    def test_missing_job_id_is_check_failed(self) -> None:
        from monitor.classifiers.url_validation import validate_instahyre_job_url

        result = validate_instahyre_job_url("https://www.instahyre.com/candidate/opportunities/")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.listing_status_reason, "invalid_url:missing_job_id")

    def test_valid_url_passes_precheck(self) -> None:
        from monitor.classifiers.url_validation import validate_instahyre_job_url

        self.assertIsNone(validate_instahyre_job_url(_VALID_URL))


class InstahyreClassifierFixtureTests(unittest.TestCase):
    def test_open_on_live_detail_shell(self) -> None:
        from monitor.classifiers.instahyre import classify_instahyre_page

        result = classify_instahyre_page(
            url=_VALID_URL,
            html=_load_fixture("instahyre_job_open.html"),
        )
        self.assertTrue(result.classification_succeeded)
        self.assertEqual(result.listing_status, "open")
        self.assertEqual(result.listing_status_reason, "open:live_detail_shell")

    def test_closed_on_reject_phrase(self) -> None:
        from monitor.classifiers.instahyre import classify_instahyre_page

        result = classify_instahyre_page(
            url=_VALID_URL,
            html=_load_fixture("instahyre_job_closed.html"),
        )
        self.assertTrue(result.classification_succeeded)
        self.assertEqual(result.listing_status, "closed")
        self.assertIn("closed:phrase:", result.listing_status_reason)

    def test_removed_on_page_not_found(self) -> None:
        from monitor.classifiers.instahyre import classify_instahyre_page

        result = classify_instahyre_page(
            url=_VALID_URL,
            html=_load_fixture("instahyre_job_removed_404.html"),
        )
        self.assertTrue(result.classification_succeeded)
        self.assertEqual(result.listing_status, "removed")

    def test_check_failed_on_login_wall(self) -> None:
        from monitor.classifiers.instahyre import classify_instahyre_page

        result = classify_instahyre_page(
            url=_VALID_URL,
            html=_load_fixture("instahyre_job_login_wall.html"),
        )
        self.assertFalse(result.classification_succeeded)
        self.assertEqual(result.listing_status, "check_failed")
        self.assertEqual(result.listing_status_reason, "auth:session_invalid")

    def test_http_404_maps_removed(self) -> None:
        from monitor.classifiers.instahyre import classify_instahyre_page

        result = classify_instahyre_page(
            url=_VALID_URL,
            html="<html><body><h1>Missing</h1></body></html>",
            http_status=404,
        )
        self.assertEqual(result.listing_status, "removed")
        self.assertEqual(result.listing_status_reason, "removed:http_404")

    def test_invalid_url_is_check_failed(self) -> None:
        from monitor.classifiers.instahyre import classify_instahyre_page

        result = classify_instahyre_page(
            url="https://example.com/jobs/1",
            html=_load_fixture("instahyre_job_open.html"),
        )
        self.assertEqual(result.listing_status, "check_failed")
        self.assertEqual(result.listing_status_reason, "invalid_url:not_instahyre_host")


class InstahyreClassifierPriorityTests(unittest.TestCase):
    def test_removed_wins_over_closed(self) -> None:
        from monitor.classifiers.instahyre import classify_instahyre_page

        html = """
        <html><body>
          <h1>Backend Engineer</h1>
          <p>404 page not found. This job is no longer accepting applications.</p>
        </body></html>
        """
        result = classify_instahyre_page(url=_VALID_URL, html=html)
        self.assertEqual(result.listing_status, "removed")

    def test_ambiguous_page_is_check_failed(self) -> None:
        from monitor.classifiers.instahyre import classify_instahyre_page

        result = classify_instahyre_page(
            url=_VALID_URL,
            html="<html><body><p>Loading...</p></body></html>",
        )
        self.assertEqual(result.listing_status, "check_failed")
        self.assertEqual(result.listing_status_reason, "dom:no_detail_shell")


if __name__ == "__main__":
    unittest.main()
