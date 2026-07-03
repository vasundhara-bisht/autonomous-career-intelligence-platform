"""LinkedIn profile DOM parsers for Outreach Intelligence (no browser lifecycle)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import html
import os
import re
from typing import Any
from urllib.parse import urlparse

_PROFILE_NAME_SELECTORS = (
    "h1.text-heading-xlarge",
    "h1.inline.t-24",
    ".pv-text-details__left-panel h1",
)
_PROFILE_HEADLINE_SELECTORS = (
    ".text-body-medium.break-words",
    ".pv-text-details__left-panel .text-body-medium",
)
_PROFILE_COMPANY_SELECTORS = (
    "button[aria-label*='Current company'] span",
    ".pv-text-details__right-panel li span",
    ".experience-item__subtitle",
)
_PROFILE_TITLE_SELECTORS = (
    "button[aria-label*='Current position'] span",
    "button[aria-label*='current position'] span",
)
_EXPERIENCE_LIST_ITEM_SELECTORS = (
    "#experience ~ div.pvs-list__outer-container ul.pvs-list > li",
    "#experience ~ div.pvs-list__outer-container li.pvs-list__item",
    "section:has(#experience) li.pvs-list__item",
    "section:has(#experience) li.artdeco-list__item",
    "#experience li.pvs-list__item",
    "#experience li.artdeco-list__item",
    "section:has(#experience) li.pvs-list__item--line-separated",
)
_EXPERIENCE_TITLE_SELECTORS = (
    ".display-flex.align-items-center.mr1.hoverable-link-text.t-bold span",
    ".hoverable-link-text.t-bold span[aria-hidden='true']",
    ".mr1.hoverable-link-text.t-bold span",
    ".t-bold span[aria-hidden='true']",
    ".t-bold span",
    ".t-bold",
)
_NESTED_ROLE_TITLE_SELECTORS = (
    ".pvs-entity__sub-components li:first-child .display-flex.align-items-center.mr1.hoverable-link-text.t-bold span",
    ".pvs-entity__sub-components li:first-child .hoverable-link-text.t-bold span",
    ".pvs-entity__sub-components li.pvs-list__item--with-top-padding:first-child .t-bold span",
    ".pvs-entity__sub-components ul.pvs-list > li:first-child .t-bold span",
    ".pvs-entity__sub-components .t-bold span[aria-hidden='true']",
    ".pvs-entity__sub-components .hoverable-link-text.t-bold span",
)
_EXPERIENCE_COMPANY_SELECTORS = (
    ".t-14.t-normal:not(.t-black--light) span[aria-hidden='true']",
    ".t-14.t-normal:not(.t-black--light) span",
    ".t-14.t-normal span[aria-hidden='true']",
    ".t-14.t-normal span",
)
_DATE_RANGE_PATTERN = re.compile(
    r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\b|"
    r"\b\d{4}\b.*\b(?:Present|present)\b|"
    r"\b\d+\s*(?:yr|yrs|mo|mos)\b",
    re.IGNORECASE,
)
_EMPLOYMENT_TYPE_PATTERN = re.compile(
    r"^(Full-time|Part-time|Contract|Internship|Self-employed|Freelance|Temporary|Volunteer)$",
    re.IGNORECASE,
)
_EMPLOYMENT_TYPE_VALUES = frozenset(
    {
        "full-time",
        "part-time",
        "contract",
        "internship",
        "self-employed",
        "freelance",
        "temporary",
        "volunteer",
    }
)
_ROLE_METADATA_TOKENS = frozenset(
    {
        "home",
        "remote",
        "hybrid",
        "on-site",
        "onsite",
    }
)
_LOGIN_MARKERS = (
    "sign in",
    "join linkedin",
    "authwall",
    "checkpoint/challenge",
)


class LinkedInProfileFetchError(RuntimeError):
    """Raised when profile content cannot be parsed."""


@dataclass(frozen=True)
class ProfileSnapshot:
    profile_url: str
    person_name: str
    headline: str
    company: str
    fetched_at: str
    current_role_title: str = ""
    current_company: str = ""
    profile_title: str = ""


@dataclass(frozen=True)
class ExperienceEntry:
    title: str
    company: str


def resolve_profile_designation(profile: ProfileSnapshot) -> str:
    """Prefer current experience title, then profile title field, then headline."""
    for value in (
        profile.current_role_title,
        profile.profile_title,
        profile.headline,
    ):
        text = str(value or "").strip()
        if text:
            return text
    return ""


def resolve_profile_company(profile: ProfileSnapshot) -> str:
    """Prefer current experience employer, then profile company field."""
    for value in (profile.current_company, profile.company):
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _profile_fetch_debug(message: str) -> None:
    if os.environ.get("DEBUG_HIRING_SIGNAL_INGEST", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    ):
        print(message)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def is_linkedin_profile_url(url: str) -> bool:
    text = str(url or "").strip()
    if not text:
        return False
    parsed = urlparse(text if "://" in text else f"https://{text}")
    host = (parsed.netloc or "").lower().replace("www.", "")
    if host != "linkedin.com":
        return False
    return (parsed.path or "").startswith("/in/")


def _is_likely_date_range(text: str) -> bool:
    cleaned = str(text or "").strip()
    if not cleaned:
        return False
    if "·" in cleaned and _DATE_RANGE_PATTERN.search(cleaned):
        return True
    return bool(_DATE_RANGE_PATTERN.search(cleaned))


def _is_employment_type(text: str) -> bool:
    return bool(_EMPLOYMENT_TYPE_PATTERN.match(str(text or "").strip()))


def normalize_company_name(text: str) -> str:
    """Strip employment-type suffixes from company text (e.g. 'Acme · Full-time')."""
    cleaned = str(text or "").strip()
    if not cleaned:
        return ""
    if _is_employment_type(cleaned):
        return ""
    if "·" in cleaned:
        left, _, right = cleaned.partition("·")
        left = left.strip()
        right = right.strip()
        if right and (
            _is_employment_type(right)
            or right.lower() in _EMPLOYMENT_TYPE_VALUES
        ):
            return left
    return cleaned


def _is_role_metadata_token(text: str) -> bool:
    return str(text or "").strip().lower() in _ROLE_METADATA_TOKENS


def _company_names_equivalent(left: str, right: str) -> bool:
    left_norm = normalize_company_name(left).casefold()
    right_norm = normalize_company_name(right).casefold()
    if not left_norm or not right_norm:
        return False
    return left_norm == right_norm


def _is_usable_company_text(text: str) -> bool:
    cleaned = str(text or "").strip()
    if not cleaned:
        return False
    if _is_likely_date_range(cleaned):
        return False
    if _is_employment_type(cleaned):
        return False
    return True


def _first_text(page_or_html_fn: Any, selectors: tuple[str, ...]) -> str:
    for selector in selectors:
        try:
            locator = page_or_html_fn.locator(selector).first
            if locator.count() > 0:
                text = str(locator.inner_text() or "").strip()
                if text:
                    return text
        except AttributeError:
            pass
        except Exception:
            pass
    return ""


def _strip_html_text(fragment: str) -> str:
    text = re.sub(r"<[^>]+>", " ", fragment)
    text = re.sub(r"\s+", " ", text).strip()
    return html.unescape(text)


def _html_first_text(html: str, class_substrings: tuple[str, ...]) -> str:
    for fragment in class_substrings:
        pattern = (
            rf'class="[^"]*{re.escape(fragment)}[^"]*"[^>]*>'
            r"(.*?)</"
        )
        match = re.search(pattern, html, re.DOTALL | re.IGNORECASE)
        if not fragment.startswith(".") and not match:
            pattern = rf"<{re.escape(fragment)}[^>]*>(.*?)</{re.escape(fragment)}>"
            match = re.search(pattern, html, re.DOTALL | re.IGNORECASE)
        if not match:
            continue
        text = _strip_html_text(match.group(1))
        if text:
            return text
    return ""


def _html_first_match(html: str, pattern: str) -> str:
    match = re.search(pattern, html, re.DOTALL | re.IGNORECASE)
    if not match:
        return ""
    return _strip_html_text(match.group(1))


def _extract_experience_region_html(html: str) -> str:
    anchor = re.search(r'\bid=["\']experience["\']', html, re.IGNORECASE)
    if not anchor:
        return ""
    start = anchor.start()
    region = html[start : start + 25_000]
    sibling = re.search(
        r'\bid=["\']experience["\'][^>]*>.*?'
        r'<div[^>]*class="[^"]*pvs-list__outer-container[^"]*"[^>]*>(.*?</ul>)',
        region,
        re.DOTALL | re.IGNORECASE,
    )
    if sibling:
        return sibling.group(1)
    section = re.search(
        r'<section[^>]*\bid=["\']experience["\'][^>]*>(.*?)</section>',
        html,
        re.DOTALL | re.IGNORECASE,
    )
    if section:
        return section.group(1)
    return region


def _extract_first_experience_item_html(region: str) -> str:
    for pattern in (
        r'<li[^>]*class="[^"]*pvs-list__item[^"]*"[^>]*>(.*?)</li>',
        r'<li[^>]*class="[^"]*artdeco-list__item[^"]*"[^>]*>(.*?)</li>',
        r"<li[^>]*>(.*?)</li>",
    ):
        match = re.search(pattern, region, re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1)
    return region


def _extract_nested_region_html(item_html: str) -> str:
    match = re.search(
        r'class="[^"]*pvs-entity__sub-components[^"]*"[^>]*>(.*)',
        item_html,
        re.DOTALL | re.IGNORECASE,
    )
    return match.group(1) if match else ""


def _iter_t_bold_texts_from_html(fragment: str) -> list[str]:
    texts: list[str] = []
    seen: set[str] = set()
    for pattern in (
        r'class="[^"]*\bt-bold\b[^"]*"[^>]*>\s*<span[^>]*>(.*?)</span>',
        r'class="[^"]*\bhoverable-link-text\b[^"]*\bt-bold\b[^"]*"[^>]*>\s*<span[^>]*>(.*?)</span>',
        r'class="[^"]*\bt-bold\b[^"]*"[^>]*>(.*?)</div>',
        r'class="[^"]*\bt-bold\b[^"]*"[^>]*>(.*?)</span>',
    ):
        for match in re.finditer(pattern, fragment, re.DOTALL | re.IGNORECASE):
            text = _strip_html_text(match.group(1))
            if not text or text in seen:
                continue
            seen.add(text)
            texts.append(text)
    return texts


def _is_usable_role_title(text: str, *, company: str = "") -> bool:
    cleaned = str(text or "").strip()
    if not cleaned:
        return False
    if _is_role_metadata_token(cleaned):
        return False
    if company and (
        cleaned == company
        or _company_names_equivalent(cleaned, company)
    ):
        return False
    if _is_likely_date_range(cleaned):
        return False
    if _is_employment_type(cleaned):
        return False
    return True


def _select_best_role_title(candidates: list[str], *, company: str) -> str:
    usable = [text for text in candidates if _is_usable_role_title(text, company=company)]
    if not usable:
        return ""
    return max(usable, key=len)


def _extract_title_from_item_html(item_html: str) -> str:
    company = _extract_company_from_item_html(item_html)
    nested_region = _extract_nested_region_html(item_html)
    if nested_region:
        nested_candidates = _iter_t_bold_texts_from_html(nested_region)
        nested_title = _select_best_role_title(nested_candidates, company=company)
        if nested_title:
            return nested_title
    return _select_best_role_title(_iter_t_bold_texts_from_html(item_html), company=company)


def _extract_company_from_item_html(item_html: str) -> str:
    for pattern in (
        r'class="[^"]*t-14[^"]*t-normal[^"]*"[^>]*>\s*<span[^>]*>(.*?)</span>',
        r'class="[^"]*t-14[^"]*t-normal[^"]*"[^>]*>(.*?)</span>',
    ):
        for match in re.finditer(pattern, item_html, re.DOTALL | re.IGNORECASE):
            text = _strip_html_text(match.group(1))
            if _is_usable_company_text(text):
                return normalize_company_name(text)
    return ""


def _parse_first_experience_from_html(html: str) -> ExperienceEntry:
    region = _extract_experience_region_html(html)
    if not region:
        return ExperienceEntry("", "")
    item_html = _extract_first_experience_item_html(region)
    return ExperienceEntry(
        title=_extract_title_from_item_html(item_html),
        company=_extract_company_from_item_html(item_html),
    )


def _extract_profile_title_from_html(html: str) -> str:
    return _html_first_match(
        html,
        r'aria-label="[^"]*current position[^"]*"[^>]*>\s*<span[^>]*>(.*?)</span>',
    )


def _scroll_experience_into_view(page: Any) -> None:
    for selector in ("#experience", "[id='experience']"):
        try:
            locator = page.locator(selector).first
            if locator.count() > 0:
                locator.scroll_into_view_if_needed(timeout=5_000)
                page.wait_for_timeout(900)
                return
        except Exception:
            pass


def _first_experience_list_item(page: Any) -> Any | None:
    for selector in _EXPERIENCE_LIST_ITEM_SELECTORS:
        try:
            locator = page.locator(selector).first
            if locator.count() > 0:
                return locator
        except Exception:
            pass
    return None


def _collect_texts_from_item(item: Any, selectors: tuple[str, ...]) -> list[str]:
    texts: list[str] = []
    seen: set[str] = set()
    for selector in selectors:
        try:
            locator = item.locator(selector)
            count = locator.count()
        except Exception:
            continue
        for index in range(count):
            try:
                text = str(locator.nth(index).inner_text() or "").strip()
            except Exception:
                continue
            if text and text not in seen:
                seen.add(text)
                texts.append(text)
    return texts


def _extract_title_from_item_page(item: Any) -> str:
    company = _extract_company_from_item_page(item)
    nested_title = _first_text(item, _NESTED_ROLE_TITLE_SELECTORS)
    if nested_title and _is_usable_role_title(nested_title, company=company):
        return nested_title

    candidates = _collect_texts_from_item(item, _EXPERIENCE_TITLE_SELECTORS)
    return _select_best_role_title(candidates, company=company)


def _extract_company_from_item_page(item: Any) -> str:
    for selector in _EXPERIENCE_COMPANY_SELECTORS:
        try:
            locator = item.locator(selector)
            count = locator.count()
        except Exception:
            continue
        for index in range(count):
            try:
                text = str(locator.nth(index).inner_text() or "").strip()
            except Exception:
                continue
            if _is_usable_company_text(text):
                return normalize_company_name(text)
    return ""


def _extract_first_experience_entry_from_page(page: Any) -> ExperienceEntry:
    item = _first_experience_list_item(page)
    if item is None:
        return ExperienceEntry("", "")
    return ExperienceEntry(
        title=_extract_title_from_item_page(item),
        company=_extract_company_from_item_page(item),
    )


def _looks_like_login_wall(page_text: str, page_url: str) -> bool:
    lowered = f"{page_url} {page_text}".lower()
    return any(marker in lowered for marker in _LOGIN_MARKERS)


def extract_profile_from_page(page: Any, *, url: str) -> ProfileSnapshot:
    """Extract profile metadata from a loaded Playwright page."""
    person_name = _first_text(page, _PROFILE_NAME_SELECTORS)
    headline = _first_text(page, _PROFILE_HEADLINE_SELECTORS)
    company = _first_text(page, _PROFILE_COMPANY_SELECTORS)
    profile_title = _first_text(page, _PROFILE_TITLE_SELECTORS)
    _scroll_experience_into_view(page)
    experience = _extract_first_experience_entry_from_page(page)
    current_role_title = experience.title
    current_company = experience.company
    page_text = ""
    try:
        page_text = str(page.inner_text("body") or "")
    except Exception:
        pass
    if _looks_like_login_wall(page_text, str(getattr(page, "url", "") or url)):
        raise LinkedInProfileFetchError(
            "LinkedIn session expired or login required on profile page."
        )
    if not person_name and not headline:
        raise LinkedInProfileFetchError(
            "Could not extract profile metadata from LinkedIn page."
        )
    _profile_fetch_debug(
        "extract_profile_from_page: "
        f"headline={headline!r} "
        f"current_role_title={current_role_title!r} "
        f"current_company={current_company!r}"
    )
    return ProfileSnapshot(
        profile_url=url.split("?")[0],
        person_name=person_name,
        headline=headline,
        company=company,
        fetched_at=_utc_now_iso(),
        current_role_title=current_role_title,
        current_company=current_company,
        profile_title=profile_title,
    )


def _selector_class_fragments(selectors: tuple[str, ...]) -> tuple[str, ...]:
    fragments: list[str] = []
    for selector in selectors:
        for part in selector.lstrip(".").split("."):
            if part and part not in fragments:
                fragments.append(part)
    return tuple(fragments)


def parse_profile_from_html(html: str, *, url: str) -> ProfileSnapshot:
    """Parse profile metadata from saved HTML (unit tests / fixtures)."""
    if _looks_like_login_wall(html, url):
        raise LinkedInProfileFetchError(
            "LinkedIn session expired or login required on profile page."
        )
    person_name = _html_first_text(html, _selector_class_fragments(_PROFILE_NAME_SELECTORS))
    if not person_name:
        person_name = _html_first_text(html, ("text-heading-xlarge",))
    headline = _html_first_text(html, _selector_class_fragments(_PROFILE_HEADLINE_SELECTORS))
    company = _html_first_text(html, _selector_class_fragments(_PROFILE_COMPANY_SELECTORS))
    experience = _parse_first_experience_from_html(html)
    profile_title = _extract_profile_title_from_html(html)
    if not person_name and not headline:
        raise LinkedInProfileFetchError(
            "Could not extract profile metadata from LinkedIn page."
        )
    return ProfileSnapshot(
        profile_url=url.split("?")[0],
        person_name=person_name,
        headline=headline,
        company=company,
        fetched_at=_utc_now_iso(),
        current_role_title=experience.title,
        current_company=experience.company,
        profile_title=profile_title,
    )
