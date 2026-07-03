"""Tests for InstaHyre monitor auth probe and session validation."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
for entry in (str(_REPO_ROOT), str(_SRC)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from monitor.browser import PageFetchResult  # noqa: E402
from monitor.instahyre_auth_probe import (  # noqa: E402
    DEFAULT_INSTAHYRE_AUTH_PROBE_URL,
    INSTAHYRE_AUTH_OK_MONITOR_RECONCILIATION,
    evaluate_instahyre_auth_probe,
    instahyre_auth_probe_url,
    reconcile_instahyre_auth_health,
    run_instahyre_auth_probe,
)
from monitor.instahyre_session import (  # noqa: E402
    evaluate_instahyre_session_fetch,
    is_valid_candidate_session_url,
)


class InstaHyreSessionValidationTests(unittest.TestCase):
    def test_is_valid_candidate_session_url_job_detail(self) -> None:
        self.assertTrue(
            is_valid_candidate_session_url(
                "https://www.instahyre.com/job-software-engineer-12345/"
            )
        )

    def test_is_valid_candidate_session_url_profile(self) -> None:
        self.assertTrue(
            is_valid_candidate_session_url(
                "https://www.instahyre.com/candidate/profile/"
            )
        )

    def test_is_valid_candidate_session_url_login_wall(self) -> None:
        self.assertFalse(
            is_valid_candidate_session_url("https://www.instahyre.com/login/")
        )


class InstaHyreAuthProbeTests(unittest.TestCase):
    def test_probe_url_default(self) -> None:
        self.assertEqual(instahyre_auth_probe_url(), DEFAULT_INSTAHYRE_AUTH_PROBE_URL)
        self.assertIn("/candidate/profile", DEFAULT_INSTAHYRE_AUTH_PROBE_URL)

    def test_auth_ok_on_profile_shell(self) -> None:
        html = (
            "<html><body>"
            "<div id='candidate-profile'><h1 class='profile-name'>Ada</h1>"
            "<a>Sign out</a></div></body></html>"
        )
        result = evaluate_instahyre_auth_probe(
            probe_url=DEFAULT_INSTAHYRE_AUTH_PROBE_URL,
            fetch=PageFetchResult(
                url=DEFAULT_INSTAHYRE_AUTH_PROBE_URL,
                html=html,
                http_status=200,
                error=None,
            ),
        )
        self.assertEqual(result.auth_health, "ok")
        self.assertEqual(result.reason, "auth:ok")

    def test_auth_ok_on_profile_url_without_shell_markers(self) -> None:
        result = evaluate_instahyre_auth_probe(
            probe_url=DEFAULT_INSTAHYRE_AUTH_PROBE_URL,
            fetch=PageFetchResult(
                url=DEFAULT_INSTAHYRE_AUTH_PROBE_URL,
                html="<html><body>profile page</body></html>",
                http_status=200,
                error=None,
            ),
        )
        self.assertEqual(result.auth_health, "ok")
        self.assertEqual(result.reason, "auth:ok")

    def test_auth_degraded_on_login_wall(self) -> None:
        html = "<html><body>Please log in to InstaHyre to continue</body></html>"
        result = evaluate_instahyre_auth_probe(
            probe_url=DEFAULT_INSTAHYRE_AUTH_PROBE_URL,
            fetch=PageFetchResult(
                url=DEFAULT_INSTAHYRE_AUTH_PROBE_URL,
                html=html,
                http_status=200,
                error=None,
            ),
        )
        self.assertEqual(result.auth_health, "degraded")
        self.assertEqual(result.reason, "auth:login_wall")

    def test_cloudflare_html_classified_as_bot_protection(self) -> None:
        html = (
            "<html><body>Just a moment..."
            "<script src='https://challenges.cloudflare.com/turnstile'></script>"
            "</body></html>"
        )
        result = evaluate_instahyre_auth_probe(
            probe_url=DEFAULT_INSTAHYRE_AUTH_PROBE_URL,
            fetch=PageFetchResult(
                url=DEFAULT_INSTAHYRE_AUTH_PROBE_URL,
                html=html,
                http_status=403,
                error=None,
            ),
        )
        self.assertEqual(result.auth_health, "degraded")
        self.assertEqual(result.reason, "probe:bot_protection")

    def test_auth_degraded_on_http_401_empty_body(self) -> None:
        result = evaluate_instahyre_auth_probe(
            probe_url=DEFAULT_INSTAHYRE_AUTH_PROBE_URL,
            fetch=PageFetchResult(
                url=DEFAULT_INSTAHYRE_AUTH_PROBE_URL,
                html="",
                http_status=401,
                error=None,
            ),
        )
        self.assertEqual(result.auth_health, "degraded")
        self.assertEqual(result.reason, "auth:http_401")

    def test_run_instahyre_auth_probe_uses_profile_url(self) -> None:
        calls: list[tuple[str, str]] = []

        def fetcher(url: str, source: str) -> PageFetchResult:
            calls.append((url, source))
            return PageFetchResult(
                url=url,
                html="<div id='candidate-profile'>profile</div>",
                http_status=200,
                error=None,
            )

        result = run_instahyre_auth_probe(fetcher)
        self.assertEqual(result.auth_health, "ok")
        self.assertEqual(calls, [(DEFAULT_INSTAHYRE_AUTH_PROBE_URL, "instahyre")])

    def test_reconcile_overrides_degraded_probe_when_jobs_succeed(self) -> None:
        class _Check:
            def __init__(self) -> None:
                self.source = "instahyre"
                self.skipped = False
                self.outcome_reason = "open:live_detail_shell"

        health, reason = reconcile_instahyre_auth_health(
            instahyre_auth_health="degraded",
            instahyre_auth_probe_reason="probe:bot_protection",
            job_results=[_Check()],
        )
        self.assertEqual(health, "ok")
        self.assertEqual(reason, INSTAHYRE_AUTH_OK_MONITOR_RECONCILIATION)

    def test_reconcile_keeps_degraded_when_all_auth_failures(self) -> None:
        class _Check:
            def __init__(self) -> None:
                self.source = "instahyre"
                self.skipped = False
                self.outcome_reason = "auth:session_invalid"

        health, reason = reconcile_instahyre_auth_health(
            instahyre_auth_health="degraded",
            instahyre_auth_probe_reason="auth:login_wall",
            job_results=[_Check()],
        )
        self.assertEqual(health, "degraded")
        self.assertEqual(reason, "auth:login_wall")

    def test_session_evaluation_reports_profile_markers(self) -> None:
        auth_health, reason = evaluate_instahyre_session_fetch(
            final_url=DEFAULT_INSTAHYRE_AUTH_PROBE_URL,
            status_code=403,
            html="<div class='candidate-profile'></div>",
        )
        self.assertEqual(auth_health, "ok")
        self.assertEqual(reason, "auth:ok")


if __name__ == "__main__":
    unittest.main()
