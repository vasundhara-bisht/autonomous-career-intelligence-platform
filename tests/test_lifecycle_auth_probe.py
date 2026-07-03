"""Tests for TD6 LinkedIn Authentication Health Probe."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
for entry in (str(_REPO_ROOT), str(_SRC)):
    if entry not in sys.path:
        sys.path.insert(0, entry)


class LinkedInAuthProbeTests(unittest.TestCase):
    def test_login_wall_is_degraded(self) -> None:
        from monitor.auth_probe import evaluate_linkedin_auth_probe
        from monitor.browser import PageFetchResult

        result = evaluate_linkedin_auth_probe(
            probe_url="https://www.linkedin.com/feed/",
            fetch=PageFetchResult(
                url="https://www.linkedin.com/feed/",
                html="<html><body><h1>Sign in</h1><p>Join LinkedIn</p></body></html>",
                http_status=200,
            ),
        )
        self.assertEqual(result.auth_health, "degraded")
        self.assertEqual(result.reason, "auth:login_wall")

    def test_successful_feed_is_ok(self) -> None:
        from monitor.auth_probe import evaluate_linkedin_auth_probe
        from monitor.browser import PageFetchResult

        result = evaluate_linkedin_auth_probe(
            probe_url="https://www.linkedin.com/feed/",
            fetch=PageFetchResult(
                url="https://www.linkedin.com/feed/",
                html="<html><body><main>Feed content</main></body></html>",
                http_status=200,
            ),
        )
        self.assertEqual(result.auth_health, "ok")
        self.assertEqual(result.reason, "auth:ok")

    def test_timeout_is_infrastructure_not_auth_degraded(self) -> None:
        from monitor.auth_probe import (
            evaluate_linkedin_auth_probe,
            is_probe_infrastructure_error,
        )
        from monitor.browser import PageFetchResult

        self.assertTrue(is_probe_infrastructure_error("timeout:goto"))
        with self.assertRaises(ValueError):
            evaluate_linkedin_auth_probe(
                probe_url="https://www.linkedin.com/feed/",
                fetch=PageFetchResult(
                    url="https://www.linkedin.com/feed/",
                    html="",
                    http_status=None,
                    error="timeout:goto",
                ),
            )

    def test_default_probe_url(self) -> None:
        from monitor.auth_probe import DEFAULT_LINKEDIN_AUTH_PROBE_URL, linkedin_auth_probe_url

        self.assertEqual(linkedin_auth_probe_url(), DEFAULT_LINKEDIN_AUTH_PROBE_URL)


if __name__ == "__main__":
    unittest.main()
