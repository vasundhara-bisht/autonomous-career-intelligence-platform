"""Unit tests for LinkedIn lifecycle classifier (T1B / Product §4A)."""

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
_VALID_URL = "https://www.linkedin.com/jobs/view/4417376197/"


def _load_fixture(name: str) -> str:
    return (_FIXTURES / name).read_text(encoding="utf-8")


class LinkedInUrlValidationTests(unittest.TestCase):
    def test_missing_job_id_is_check_failed(self) -> None:
        from monitor.classifiers.url_validation import validate_linkedin_job_url

        result = validate_linkedin_job_url("https://www.linkedin.com/jobs/collections/")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertFalse(result.classification_succeeded)
        self.assertEqual(result.listing_status, "check_failed")
        self.assertEqual(result.listing_status_reason, "invalid_url:missing_job_id")

    def test_empty_url_is_check_failed(self) -> None:
        from monitor.classifiers.url_validation import validate_linkedin_job_url

        result = validate_linkedin_job_url("   ")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.listing_status_reason, "invalid_url:empty")

    def test_valid_url_passes_precheck(self) -> None:
        from monitor.classifiers.url_validation import validate_linkedin_job_url

        self.assertIsNone(validate_linkedin_job_url(_VALID_URL))


class LinkedInClassifierFixtureTests(unittest.TestCase):
    def test_open_live_shell_with_apply(self) -> None:
        from monitor.classifiers.linkedin import classify_linkedin_page

        result = classify_linkedin_page(
            url=_VALID_URL,
            html=_load_fixture("linkedin_job_open_live_shell.html"),
        )
        self.assertTrue(result.classification_succeeded)
        self.assertEqual(result.listing_status, "open")
        self.assertEqual(result.listing_status_reason, "open:live_shell_apply")

    def test_closed_on_live_shell_with_closure_phrase(self) -> None:
        from monitor.classifiers.linkedin import classify_linkedin_page

        result = classify_linkedin_page(
            url=_VALID_URL,
            html=_load_fixture("linkedin_job_closed_phrase.html"),
        )
        self.assertTrue(result.classification_succeeded)
        self.assertEqual(result.listing_status, "closed")
        self.assertIn("closed:phrase:", result.listing_status_reason)

    def test_removed_on_error_shell(self) -> None:
        from monitor.classifiers.linkedin import classify_linkedin_page

        result = classify_linkedin_page(
            url=_VALID_URL,
            html=_load_fixture("linkedin_job_removed_error_shell.html"),
        )
        self.assertTrue(result.classification_succeeded)
        self.assertEqual(result.listing_status, "removed")

    def test_check_failed_on_login_wall(self) -> None:
        from monitor.classifiers.linkedin import classify_linkedin_page

        result = classify_linkedin_page(
            url=_VALID_URL,
            html=_load_fixture("linkedin_job_login_wall.html"),
        )
        self.assertFalse(result.classification_succeeded)
        self.assertEqual(result.listing_status, "check_failed")
        self.assertEqual(result.listing_status_reason, "auth:login_wall")

    def test_error_shell_with_closure_maps_removed_not_closed(self) -> None:
        from monitor.classifiers.linkedin import classify_linkedin_page

        result = classify_linkedin_page(
            url=_VALID_URL,
            html=_load_fixture("linkedin_job_error_shell_with_closure.html"),
        )
        self.assertTrue(result.classification_succeeded)
        self.assertEqual(result.listing_status, "removed")
        self.assertEqual(result.listing_status_reason, "removed:error_shell_with_closure")

    def test_closed_with_footer_signin_is_not_login_wall(self) -> None:
        from monitor.classifiers.linkedin import classify_linkedin_page

        result = classify_linkedin_page(
            url=_VALID_URL,
            html=_load_fixture("linkedin_job_closed_with_footer_signin.html"),
        )
        self.assertTrue(result.classification_succeeded)
        self.assertEqual(result.listing_status, "closed")
        self.assertIn("closed:phrase:", result.listing_status_reason)

    def test_closed_on_title_and_metadata_without_description(self) -> None:
        from monitor.classifiers.linkedin import classify_linkedin_page

        result = classify_linkedin_page(
            url=_VALID_URL,
            html=_load_fixture("linkedin_job_closed_title_metadata.html"),
        )
        self.assertTrue(result.classification_succeeded)
        self.assertEqual(result.listing_status, "closed")
        self.assertIn("closed:phrase:", result.listing_status_reason)

    def test_closed_on_flagship3_layout_with_closure_phrase(self) -> None:
        from monitor.classifiers.linkedin import classify_linkedin_page

        result = classify_linkedin_page(
            url="https://www.linkedin.com/jobs/view/4409792769/",
            html=_load_fixture("linkedin_job_closed_flagship3.html"),
        )
        self.assertTrue(result.classification_succeeded)
        self.assertEqual(result.listing_status, "closed")
        self.assertEqual(
            result.listing_status_reason,
            "closed:phrase:no_longer_accepting_applications",
        )

    def test_closed_on_flagship3_no_h1_with_page_title(self) -> None:
        from monitor.classifiers.linkedin import classify_linkedin_page

        result = classify_linkedin_page(
            url="https://www.linkedin.com/jobs/view/4416317709/",
            html=_load_fixture("linkedin_job_closed_flagship3_no_h1.html"),
        )
        self.assertTrue(result.classification_succeeded)
        self.assertEqual(result.listing_status, "closed")
        self.assertEqual(
            result.listing_status_reason,
            "closed:phrase:no_longer_accepting_applications",
        )

    def test_page_title_alone_without_shell_is_not_live_shell(self) -> None:
        from monitor.classifiers.linkedin import classify_linkedin_page

        html = """
        <html><head><title>Product Manager | fam | LinkedIn</title></head>
        <body><main><p>No longer accepting applications</p></main></body></html>
        """
        result = classify_linkedin_page(
            url="https://www.linkedin.com/jobs/view/4416317709/",
            html=html,
        )
        self.assertEqual(result.listing_status, "removed")
        self.assertEqual(result.listing_status_reason, "removed:error_shell_with_closure")

    def test_authwall_url_is_login_wall_even_with_shell_markers(self) -> None:
        from monitor.classifiers.linkedin import classify_linkedin_page

        result = classify_linkedin_page(
            url="https://www.linkedin.com/authwall?session_redirect=/jobs/view/123/",
            html=_load_fixture("linkedin_job_closed_phrase.html"),
        )
        self.assertEqual(result.listing_status, "check_failed")
        self.assertEqual(result.listing_status_reason, "auth:login_wall")

    def test_http_404_maps_removed(self) -> None:
        from monitor.classifiers.linkedin import classify_linkedin_page

        result = classify_linkedin_page(
            url=_VALID_URL,
            html="<html><body><h1>Not found</h1></body></html>",
            http_status=404,
        )
        self.assertEqual(result.listing_status, "removed")
        self.assertEqual(result.listing_status_reason, "removed:http_404")

    def test_invalid_url_before_navigation_is_check_failed(self) -> None:
        from monitor.classifiers.linkedin import classify_linkedin_page

        result = classify_linkedin_page(
            url="https://example.com/not-linkedin",
            html=_load_fixture("linkedin_job_open_live_shell.html"),
        )
        self.assertEqual(result.listing_status, "check_failed")
        self.assertEqual(result.listing_status_reason, "invalid_url:not_linkedin_host")

    def test_live_shell_without_apply_is_check_failed(self) -> None:
        from monitor.classifiers.linkedin import classify_linkedin_page

        html = """
        <html><body>
          <h1>Engineer</h1>
          <div class="job-details-jobs-unified-top-card__primary-description-container">Meta</div>
          <div class="jobs-description"><p>Role details</p></div>
        </body></html>
        """
        result = classify_linkedin_page(url=_VALID_URL, html=html)
        self.assertEqual(result.listing_status, "check_failed")
        self.assertEqual(result.listing_status_reason, "dom:no_apply_signal")


class LinkedInClassifierPriorityTests(unittest.TestCase):
    def test_removed_wins_over_closed_on_non_live_shell(self) -> None:
        from monitor.classifiers.linkedin import classify_linkedin_page

        html = """
        <html><body>
          <p>Page not found. No longer accepting applications.</p>
        </body></html>
        """
        result = classify_linkedin_page(url=_VALID_URL, html=html)
        self.assertEqual(result.listing_status, "removed")

    def test_no_m15_special_case_live_shell_closure_is_closed(self) -> None:
        from monitor.classifiers.linkedin import classify_linkedin_page

        html = """
        <html><body>
          <h1>Product Manager</h1>
          <div class="jobs-description">
            <p>This job is no longer available but we're no longer accepting applications.</p>
          </div>
          <div class="job-details-jobs-unified-top-card__primary-description-container">Acme</div>
        </body></html>
        """
        result = classify_linkedin_page(url=_VALID_URL, html=html)
        self.assertEqual(result.listing_status, "closed")


class LinkedInAppliedDetectionTests(unittest.TestCase):
    def test_legacy_applied_status_span(self) -> None:
        from monitor.classifiers.linkedin import detect_linkedin_user_applied

        html = _load_fixture("linkedin_job_applied_status.html")
        self.assertTrue(detect_linkedin_user_applied(html))

    def test_flagship3_application_submitted(self) -> None:
        from monitor.classifiers.linkedin import detect_linkedin_user_applied

        html = _load_fixture("linkedin_job_applied_flagship3_submitted.html")
        self.assertTrue(detect_linkedin_user_applied(html))

    def test_open_listing_without_applied_signal(self) -> None:
        from monitor.classifiers.linkedin import detect_linkedin_user_applied

        html = """
        <html><body><main>
          <h1>Product Manager</h1>
          <div class="job-details-jobs-unified-top-card__primary-description-container">Acme</div>
          <div class="jobs-description"><p>Role details</p></div>
          <button class="jobs-apply-button">Apply</button>
        </main></body></html>
        """
        self.assertFalse(detect_linkedin_user_applied(html))


if __name__ == "__main__":
    unittest.main()
