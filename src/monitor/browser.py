"""Shared Playwright session for Scheduler B job page fetches (T1C)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import paths


class MonitorBrowserError(RuntimeError):
    """Raised when the monitor browser cannot start (missing auth, Playwright failure)."""


@dataclass(frozen=True)
class PageFetchResult:
    url: str
    html: str
    http_status: int | None
    error: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.error is None and bool(self.html)


def _headless_enabled() -> bool:
    raw = os.environ.get("LIFECYCLE_MONITOR_HEADLESS", "1").strip().lower()
    return raw not in ("0", "false", "no")


def _goto_timeout_ms() -> int:
    raw = os.environ.get("LIFECYCLE_MONITOR_GOTO_TIMEOUT_MS", "45000").strip()
    try:
        return max(1000, int(raw))
    except ValueError:
        return 45000


def _post_goto_wait_ms() -> int:
    raw = os.environ.get("LIFECYCLE_MONITOR_POST_GOTO_WAIT_MS", "1500").strip()
    try:
        return max(0, int(raw))
    except ValueError:
        return 1500


def _linkedin_shell_wait_ms() -> int:
    raw = os.environ.get("LIFECYCLE_MONITOR_LINKEDIN_SHELL_WAIT_MS", "5000").strip()
    try:
        return max(0, int(raw))
    except ValueError:
        return 5000


_LINKEDIN_SHELL_SELECTORS = ", ".join(
    (
        "div.job-details-jobs-unified-top-card__primary-description-container",
        "div.jobs-unified-top-card",
        "div.jobs-details-top-card",
        "h1",
        "div.jobs-description",
        "section.show-more-less-html",
    )
)


def _wait_for_linkedin_job_shell(page: Any) -> None:
    """Bounded wait for job-shell markers; non-fatal on timeout."""
    timeout_ms = _linkedin_shell_wait_ms()
    if timeout_ms <= 0:
        return
    try:
        page.wait_for_selector(_LINKEDIN_SHELL_SELECTORS, timeout=timeout_ms)
    except Exception:
        pass


def _require_auth_file(path: Any, *, label: str) -> None:
    if not path.is_file():
        raise MonitorBrowserError(f"missing_auth:{label}")


class MonitorBrowser:
    """Per-run Playwright browser with LinkedIn + Instahyre authenticated contexts."""

    def __init__(self, *, headless: bool | None = None) -> None:
        self._headless = _headless_enabled() if headless is None else headless
        self._playwright: Any = None
        self._browser: Any = None
        self._linkedin_context: Any = None
        self._instahyre_context: Any = None

    def __enter__(self) -> MonitorBrowser:
        from playwright.sync_api import sync_playwright

        _require_auth_file(paths.linkedin_auth_json(), label="linkedin_auth.json")
        _require_auth_file(paths.instahyre_auth_json(), label="instahyre_auth.json")

        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=self._headless)
        self._linkedin_context = self._browser.new_context(
            storage_state=str(paths.linkedin_auth_json())
        )
        self._instahyre_context = self._browser.new_context(
            storage_state=str(paths.instahyre_auth_json())
        )
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        for context in (self._linkedin_context, self._instahyre_context):
            if context is not None:
                try:
                    context.close()
                except Exception:
                    pass
        if self._browser is not None:
            try:
                self._browser.close()
            except Exception:
                pass
        if self._playwright is not None:
            try:
                self._playwright.stop()
            except Exception:
                pass
        self._playwright = None
        self._browser = None
        self._linkedin_context = None
        self._instahyre_context = None

    def fetch_job_page(self, url: str, source: str) -> PageFetchResult:
        """Navigate to a stored job URL and return rendered HTML."""
        src = (source or "").strip().lower()
        if src == "linkedin":
            context = self._linkedin_context
        elif src == "instahyre":
            context = self._instahyre_context
        else:
            return PageFetchResult(url=url, html="", http_status=None, error="unsupported_source")

        if context is None:
            return PageFetchResult(url=url, html="", http_status=None, error="browser:not_started")

        page = context.new_page()
        timeout_ms = _goto_timeout_ms()
        wait_ms = _post_goto_wait_ms()
        try:
            response = page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
            if wait_ms:
                page.wait_for_timeout(wait_ms)
            if src == "linkedin":
                _wait_for_linkedin_job_shell(page)
            html = page.content()
            status = int(response.status) if response is not None else None
            final_url = page.url or url
            return PageFetchResult(url=final_url, html=html, http_status=status, error=None)
        except Exception as exc:
            reason = type(exc).__name__.lower()
            if "timeout" in str(exc).lower() or reason.endswith("timeouterror"):
                return PageFetchResult(
                    url=url,
                    html="",
                    http_status=None,
                    error="timeout:goto",
                )
            return PageFetchResult(
                url=url,
                html="",
                http_status=None,
                error=f"runtime:{reason}",
            )
        finally:
            try:
                page.close()
            except Exception:
                pass
