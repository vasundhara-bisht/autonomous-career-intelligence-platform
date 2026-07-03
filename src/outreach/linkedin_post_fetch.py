"""Playwright-backed LinkedIn post retrieval for Outreach Intelligence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Any

import paths

from outreach.contact_extract import extract_emails_from_text
from outreach.linkedin_profile_fetch import (
    LinkedInProfileFetchError,
    ProfileSnapshot,
    extract_profile_from_page,
    is_linkedin_profile_url,
)

BODY_TEXT_MAX_CHARS = 12_000

_POST_BODY_SELECTORS = (
    ".feed-shared-update-v2__description",
    ".update-components-text",
    ".feed-shared-text",
    "[data-test-id='main-feed-activity-card'] .break-words",
)
_AUTHOR_NAME_SELECTORS = (
    ".update-components-actor__name span[aria-hidden='true']",
    ".update-components-actor__name",
    ".feed-shared-actor__name",
)
_AUTHOR_LINK_SELECTORS = (
    "a.update-components-actor__meta-link",
    "a.feed-shared-actor__container-link",
    ".update-components-actor__meta-link",
)
_LOGIN_MARKERS = (
    "sign in",
    "join linkedin",
    "authwall",
    "checkpoint/challenge",
)


class LinkedInPostFetchError(RuntimeError):
    """Raised when post content cannot be retrieved."""


@dataclass(frozen=True)
class PostSnapshot:
    url: str
    body_text: str
    author_name: str
    author_profile_url: str
    fetched_at: str
    post_timestamp: str = ""


@dataclass(frozen=True)
class HiringSignalContext:
    post: PostSnapshot
    profile: ProfileSnapshot | None
    detected_emails: list[str]
    profile_warning: str | None = None


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _first_text(page_or_soup: Any, selectors: tuple[str, ...]) -> str:
    for selector in selectors:
        try:
            locator = page_or_soup.locator(selector).first
            if locator.count() > 0:
                text = str(locator.inner_text() or "").strip()
                if text:
                    return text
        except AttributeError:
            pass
    return ""


def _first_href(page_or_soup: Any, selectors: tuple[str, ...]) -> str:
    for selector in selectors:
        try:
            locator = page_or_soup.locator(selector).first
            if locator.count() > 0:
                href = str(locator.get_attribute("href") or "").strip()
                if href:
                    if href.startswith("/"):
                        return f"https://www.linkedin.com{href.split('?')[0]}"
                    return href.split("?")[0]
        except AttributeError:
            pass
    return ""


def _cap_body_text(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", str(text or "").strip())
    if len(cleaned) <= BODY_TEXT_MAX_CHARS:
        return cleaned
    return cleaned[:BODY_TEXT_MAX_CHARS].rstrip() + "…"


def _looks_like_login_wall(page_text: str, page_url: str) -> bool:
    lowered = f"{page_url} {page_text}".lower()
    return any(marker in lowered for marker in _LOGIN_MARKERS)


def _auth_path_or_raise() -> Any:
    auth_path = paths.linkedin_auth_json()
    if not auth_path.is_file():
        raise LinkedInPostFetchError(
            f"Missing LinkedIn session at {auth_path}. "
            "Run save_linkedin_session() from scraper/linkedin.py first."
        )
    return auth_path


def extract_post_snapshot_from_page(page: Any, *, url: str) -> PostSnapshot:
    """Extract post content from a loaded Playwright page."""
    body_text = _cap_body_text(_first_text(page, _POST_BODY_SELECTORS))
    author_name = _first_text(page, _AUTHOR_NAME_SELECTORS)
    author_profile_url = _first_href(page, _AUTHOR_LINK_SELECTORS)
    page_text = ""
    try:
        page_text = str(page.inner_text("body") or "")
    except Exception:
        pass
    if _looks_like_login_wall(page_text, str(getattr(page, "url", "") or "")):
        raise LinkedInPostFetchError(
            "LinkedIn session expired or login required. "
            "Refresh data/linkedin_auth.json via save_linkedin_session()."
        )
    if not body_text:
        raise LinkedInPostFetchError(
            "Could not extract post text from LinkedIn page. Enter details manually."
        )
    return PostSnapshot(
        url=url,
        body_text=body_text,
        author_name=author_name,
        author_profile_url=author_profile_url,
        fetched_at=_utc_now_iso(),
    )


def _html_first_text(html: str, class_substrings: tuple[str, ...]) -> str:
    for fragment in class_substrings:
        pattern = (
            rf'class="[^"]*{re.escape(fragment)}[^"]*"[^>]*>'
            r"(.*?)</"
        )
        match = re.search(pattern, html, re.DOTALL | re.IGNORECASE)
        if not match:
            continue
        text = re.sub(r"<[^>]+>", " ", match.group(1))
        text = re.sub(r"\s+", " ", text).strip()
        if text:
            return text
    return ""


def _html_first_href(html: str, class_substrings: tuple[str, ...]) -> str:
    for fragment in class_substrings:
        pattern = (
            rf'<a[^>]*class="[^"]*{re.escape(fragment)}[^"]*"[^>]*href="([^"]+)"'
        )
        match = re.search(pattern, html, re.IGNORECASE)
        if match:
            href = match.group(1).strip()
            if href.startswith("/"):
                return f"https://www.linkedin.com{href.split('?')[0]}"
            return href.split("?")[0]
    return ""


def parse_post_snapshot_from_html(html: str, *, url: str) -> PostSnapshot:
    """Parse post content from saved HTML (unit tests / fixtures)."""
    body_text = _cap_body_text(
        _html_first_text(
            html,
            tuple(selector.lstrip(".") for selector in _POST_BODY_SELECTORS),
        )
    )
    author_name = _html_first_text(
        html,
        tuple(selector.lstrip(".") for selector in _AUTHOR_NAME_SELECTORS),
    )
    author_profile_url = _html_first_href(
        html,
        tuple(selector.lstrip("a.").lstrip(".") for selector in _AUTHOR_LINK_SELECTORS),
    )
    if _looks_like_login_wall(html, url):
        raise LinkedInPostFetchError(
            "LinkedIn session expired or login required. "
            "Refresh data/linkedin_auth.json via save_linkedin_session()."
        )
    if not body_text:
        raise LinkedInPostFetchError(
            "Could not extract post text from LinkedIn page. Enter details manually."
        )
    return PostSnapshot(
        url=url,
        body_text=body_text,
        author_name=author_name,
        author_profile_url=author_profile_url,
        fetched_at=_utc_now_iso(),
    )


def extract_post_snapshot_from_html(html: str, *, url: str) -> PostSnapshot:
    """Backward-compatible alias for fixture parsing."""
    return parse_post_snapshot_from_html(html, url=url)


def _enrich_profile_on_page(
    page: Any,
    *,
    profile_url: str,
    timeout_ms: int,
) -> tuple[ProfileSnapshot | None, str | None]:
    if not is_linkedin_profile_url(profile_url):
        return None, None
    try:
        page.goto(profile_url, wait_until="domcontentloaded", timeout=timeout_ms)
        page.wait_for_timeout(1_500)
        return extract_profile_from_page(page, url=profile_url), None
    except LinkedInProfileFetchError as exc:
        return None, f"Profile enrichment unavailable: {exc}"
    except Exception as exc:
        return None, f"Profile enrichment unavailable: {exc}"


def fetch_hiring_signal_context(
    url: str,
    *,
    enrich_profile: bool = True,
    timeout_ms: int = 30_000,
) -> HiringSignalContext:
    """Fetch post and optional author profile in a single Playwright session."""
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright

    from outreach.linkedin_post_url import validate_linkedin_post_url

    normalized = validate_linkedin_post_url(url)
    auth_path = _auth_path_or_raise()

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=False)
            try:
                context = browser.new_context(storage_state=str(auth_path))
                page = context.new_page()
                profile: ProfileSnapshot | None = None
                profile_warning: str | None = None
                page.goto(normalized, wait_until="domcontentloaded", timeout=timeout_ms)
                page.wait_for_timeout(1_500)
                post = extract_post_snapshot_from_page(page, url=normalized)

                if enrich_profile and post.author_profile_url:
                    profile, profile_warning = _enrich_profile_on_page(
                        page,
                        profile_url=post.author_profile_url,
                        timeout_ms=timeout_ms,
                    )

                detected_emails = extract_emails_from_text(post.body_text)
                return HiringSignalContext(
                    post=post,
                    profile=profile,
                    detected_emails=detected_emails,
                    profile_warning=profile_warning,
                )
            except PlaywrightTimeoutError as exc:
                partial = _cap_body_text(_first_text(page, _POST_BODY_SELECTORS))
                if partial:
                    raise LinkedInPostFetchError(
                        f"LinkedIn fetch timed out. Partial text captured ({len(partial)} chars)."
                    ) from exc
                raise LinkedInPostFetchError(
                    "LinkedIn fetch timed out. Try again or enter details manually."
                ) from exc
            finally:
                browser.close()
    except LinkedInPostFetchError:
        raise
    except Exception as exc:
        raise LinkedInPostFetchError(
            f"LinkedIn fetch failed: {exc}"
        ) from exc


def fetch_linkedin_post(url: str, *, timeout_ms: int = 30_000) -> PostSnapshot:
    """Fetch a LinkedIn post using the saved session in data/linkedin_auth.json."""
    return fetch_hiring_signal_context(url, enrich_profile=False, timeout_ms=timeout_ms).post
