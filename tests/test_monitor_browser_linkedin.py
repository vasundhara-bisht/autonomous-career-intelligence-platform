"""Unit tests for LinkedIn monitor browser shell wait (Tier 1 remediation)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
for entry in (str(_REPO_ROOT), str(_SRC)):
    if entry not in sys.path:
        sys.path.insert(0, entry)


class LinkedInShellWaitTests(unittest.TestCase):
    def test_wait_for_linkedin_job_shell_calls_selector_wait(self) -> None:
        from monitor.browser import _wait_for_linkedin_job_shell

        page = MagicMock()
        _wait_for_linkedin_job_shell(page)
        page.wait_for_selector.assert_called_once()
        args, kwargs = page.wait_for_selector.call_args
        self.assertIn("jobs-description", args[0])
        self.assertEqual(kwargs["timeout"], 5000)

    def test_wait_for_linkedin_job_shell_ignores_timeout(self) -> None:
        from monitor.browser import _wait_for_linkedin_job_shell

        page = MagicMock()
        page.wait_for_selector.side_effect = TimeoutError("selector timeout")
        _wait_for_linkedin_job_shell(page)
        page.wait_for_selector.assert_called_once()

    def test_fetch_job_page_waits_for_linkedin_shell_before_content(self) -> None:
        from monitor.browser import MonitorBrowser

        page = MagicMock()
        page.goto.return_value = MagicMock(status=200)
        page.url = "https://www.linkedin.com/jobs/view/123/"
        page.content.return_value = "<html><body>ok</body></html>"

        context = MagicMock()
        context.new_page.return_value = page

        browser = MonitorBrowser(headless=True)
        browser._linkedin_context = context

        result = browser.fetch_job_page(
            "https://www.linkedin.com/jobs/view/123/",
            "linkedin",
        )
        self.assertIsNone(result.error)
        page.wait_for_selector.assert_called_once()
        page.content.assert_called_once()


if __name__ == "__main__":
    unittest.main()
