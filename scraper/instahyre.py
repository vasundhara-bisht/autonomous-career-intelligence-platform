"""
Instahyre feed-driven acquisition (Playwright).

Two curated feeds only — visible opportunity cards → validated detail pages.
Hard-rejects invalid jobs before they enter the pipeline.

Invoked from main.py unless INSTAHYRE_MAX_RUNS=0.
Session: instahyre_auth.json (storage_state, gitignored).
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any
from urllib.parse import urljoin, urlparse

from playwright.sync_api import Page, sync_playwright

from agent.job_identity import extract_instahyre_job_id, generate_job_key_v2
from scraper.instahyre_logging import (
    debug_dom_enabled,
    log_debug,
    log_debug_rejection,
    log_fail,
    log_feed_debug_metrics,
    log_ok,
    log_warn,
)

import paths

_AUTH_PATH = str(paths.instahyre_auth_json())
_ORIGIN = "https://www.instahyre.com"
_FEED_MATCHING_URL = f"{_ORIGIN}/candidate/opportunities/?matching=true"
# Phase B: Interested filter (status=1) — state sync only, not a discovery feed.
_INTERESTED_SYNC_URL = f"{_ORIGIN}/candidate/opportunities/?matching=true&status=1"
_FEED_PM_SEARCH_URL = (
    f"{_ORIGIN}/search-jobs?company_size=0&isLandingPage=true"
    f"&job_functions=%2Fapi%2Fv1%2Fjob_category%2F2&job_type=1"
    f"&location=Work+From+Home,Anywhere+in+India&offset=20&search=true&years=4.5"
)
# Feed 2 catalog id; allowlist alias for scrape validation.
_FEED_PM_CURATED_URL = _FEED_PM_SEARCH_URL
_OPPORTUNITY_URL_RE = re.compile(r"^/job-(\d+)(?:/|$|-)", re.IGNORECASE)
_STABLE_JOB_PATH_RE = re.compile(r"/job-(\d+)(?:/|$|-)", re.IGNORECASE)
_DETAIL_REJECT_PHRASES = (
    "page not found",
    "404",
    "no longer accepting applications",
)
_FEED_ID_MATCHING_PERSONALIZED = "matching_personalized"
_FEED_ID_PM_CURATED_SEARCH = "pm_curated_search"
_FEED_ID_INTERESTED_SYNC = "interested_sync"
_PAGINATED_FEED_IDS = frozenset(
    {
        _FEED_ID_MATCHING_PERSONALIZED,
        _FEED_ID_PM_CURATED_SEARCH,
        _FEED_ID_INTERESTED_SYNC,
    }
)

# Effectively uncapped for paginated feeds; override via INSTAHYRE_MAX_JOBS_PER_FEED.
_DEFAULT_MAX_JOBS_PER_FEED = 10_000


def _max_jobs_per_feed() -> int:
    """Per-feed detail cap. Env unset → high default (pagination-safe). Env 0 → uncapped."""
    raw = os.environ.get("INSTAHYRE_MAX_JOBS_PER_FEED", "").strip()
    if not raw:
        return _DEFAULT_MAX_JOBS_PER_FEED
    try:
        val = int(raw)
    except ValueError:
        return _DEFAULT_MAX_JOBS_PER_FEED
    if val <= 0:
        return _DEFAULT_MAX_JOBS_PER_FEED
    return val


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_truthy(name: str, *, default: bool = False) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class FeedDiscoverySettings:
    """Per-feed list discovery tuning (paginated feeds vs Feed 1 scroll fallback vs legacy)."""

    feed_id: str
    deep_discovery: bool
    traversal_mode: str  # "pagination" | "scroll"
    max_pages: int
    page_min_new_ratio: float
    page_transition_wait_ms: int
    page_settle_ms: int
    scroll_max_cycles: int
    stable_rounds: int
    list_wait_ms: int
    post_scroll_wait_ms: int
    min_scroll_cycles_before_stable: int
    initial_settle_ms: int


def _paginated_discovery_settings(feed_id: str) -> FeedDiscoverySettings:
    """Shared pagination tuning for Feed 1 and Feed 2 (search-jobs)."""
    return FeedDiscoverySettings(
        feed_id=feed_id,
        deep_discovery=True,
        traversal_mode="pagination",
        max_pages=_env_int("INSTAHYRE_MAX_PAGES", 5),
        page_min_new_ratio=float(
            os.environ.get("INSTAHYRE_PAGE_MIN_NEW_RATIO", "0.15").strip() or "0.15"
        ),
        page_transition_wait_ms=_env_int("INSTAHYRE_PAGE_TRANSITION_WAIT_MS", 10_000),
        page_settle_ms=_env_int("INSTAHYRE_PAGE_SETTLE_MS", 1_500),
        scroll_max_cycles=_env_int("INSTAHYRE_SCROLL_MAX_CYCLES", 18),
        stable_rounds=_env_int("INSTAHYRE_STABLE_ROUNDS", 5),
        list_wait_ms=_env_int("INSTAHYRE_LIST_WAIT_MS", 55_000),
        post_scroll_wait_ms=_env_int("INSTAHYRE_POST_SCROLL_WAIT_MS", 2_000),
        min_scroll_cycles_before_stable=_env_int(
            "INSTAHYRE_MATCHING_MIN_SCROLL_CYCLES", 4
        ),
        initial_settle_ms=_env_int("INSTAHYRE_MATCHING_INITIAL_SETTLE_MS", 1_800),
    )


def discovery_settings_for_feed(feed_id: str) -> FeedDiscoverySettings:
    """
    Paginated feeds (matching_personalized, pm_curated_search): reuse Feed 1 pagination.
    Feed 1 only: INSTAHYRE_MATCHING_SCROLL_FALLBACK=1 restores scroll deep-discovery.
    """
    fid = str(feed_id or "").strip() or "feed"
    if fid == _FEED_ID_MATCHING_PERSONALIZED:
        if _env_truthy("INSTAHYRE_MATCHING_SCROLL_FALLBACK", default=False):
            return FeedDiscoverySettings(
                feed_id=fid,
                deep_discovery=True,
                traversal_mode="scroll",
                max_pages=_env_int("INSTAHYRE_MAX_PAGES", 5),
                page_min_new_ratio=float(
                    os.environ.get("INSTAHYRE_PAGE_MIN_NEW_RATIO", "0.15").strip()
                    or "0.15"
                ),
                page_transition_wait_ms=_env_int(
                    "INSTAHYRE_PAGE_TRANSITION_WAIT_MS", 10_000
                ),
                page_settle_ms=_env_int("INSTAHYRE_PAGE_SETTLE_MS", 1_500),
                scroll_max_cycles=_env_int("INSTAHYRE_SCROLL_MAX_CYCLES", 18),
                stable_rounds=_env_int("INSTAHYRE_STABLE_ROUNDS", 5),
                list_wait_ms=_env_int("INSTAHYRE_LIST_WAIT_MS", 55_000),
                post_scroll_wait_ms=_env_int("INSTAHYRE_POST_SCROLL_WAIT_MS", 2_000),
                min_scroll_cycles_before_stable=_env_int(
                    "INSTAHYRE_MATCHING_MIN_SCROLL_CYCLES", 4
                ),
                initial_settle_ms=_env_int("INSTAHYRE_MATCHING_INITIAL_SETTLE_MS", 1_800),
            )
        return _paginated_discovery_settings(fid)
    if fid == _FEED_ID_PM_CURATED_SEARCH:
        return _paginated_discovery_settings(fid)
    if fid == _FEED_ID_INTERESTED_SYNC:
        return _paginated_discovery_settings(fid)
    return FeedDiscoverySettings(
        feed_id=fid,
        deep_discovery=False,
        traversal_mode="scroll",
        max_pages=1,
        page_min_new_ratio=0.15,
        page_transition_wait_ms=10_000,
        page_settle_ms=1_500,
        scroll_max_cycles=_env_int("INSTAHYRE_SCROLL_MAX_CYCLES", 12),
        stable_rounds=_env_int("INSTAHYRE_STABLE_ROUNDS", 3),
        list_wait_ms=_env_int("INSTAHYRE_LIST_WAIT_MS", 45_000),
        post_scroll_wait_ms=_env_int("INSTAHYRE_POST_SCROLL_WAIT_MS", 1_200),
        min_scroll_cycles_before_stable=0,
        initial_settle_ms=1_500,
    )

_FEED_SIGNAL_JS = """
() => ({
  employerBlocks: document.querySelectorAll('.candidate-opportunities .employer-block').length,
  interestedButtons: document.querySelectorAll('.candidate-opportunities button.button-interested').length,
})
"""

_DOM_BLOCKS_JS = """
() => {
  const root = document.querySelector('.candidate-opportunities') || document.body;
  const blocks = Array.from(root.querySelectorAll('.employer-block'));
  return blocks.map((block, index) => {
    const cardText = (block.innerText || '').trim();
    const tags = Array.from(
      block.querySelectorAll('ul.candidate-opp-keywords li, .candidate-opp-keywords li')
    )
      .map((li) => (li.innerText || '').trim())
      .filter(Boolean);
    return { index, cardText, tags };
  });
}
"""

_DOM_BLOCKS_HARVEST_JS = """
() => {
  const jobRe = /\\/job-(\\d+)(?:\\/|$|-)/i;
  const root =
    document.querySelector('.candidate-opportunities') ||
    document.querySelector('main') ||
    document.body;
  const blocks = Array.from(root.querySelectorAll('.employer-block'));
  return blocks.map((block, index) => {
    const cardText = (block.innerText || '').trim();
    const tags = Array.from(
      block.querySelectorAll('ul.candidate-opp-keywords li, .candidate-opp-keywords li')
    )
      .map((li) => (li.innerText || '').trim())
      .filter(Boolean);
    let opportunityPath = '';
    const anchors = Array.from(block.querySelectorAll('a[href]'));
    const viewLink = anchors.find((a) => {
      const href = a.getAttribute('href') || '';
      if (!jobRe.test(href)) return false;
      return (a.innerText || '').trim().toLowerCase().includes('view');
    });
    const jobLink =
      viewLink || anchors.find((a) => jobRe.test(a.getAttribute('href') || ''));
    if (jobLink) {
      const href = (jobLink.getAttribute('href') || '').trim();
      if (href.startsWith('/')) {
        opportunityPath = href;
      } else if (href.includes('/job-')) {
        const m = href.match(/\\/job-\\d+[^?#]*/i);
        opportunityPath = m ? m[0] : '';
      }
    }
    return { index, cardText, tags, opportunityPath };
  });
}
"""

_ANGULAR_OPPS_JS = """
() => {
  if (!window.angular) return { error: 'no_angular' };
  const el = document.querySelector('[ng-controller="candidateOpportunityCtrl"]');
  if (!el) return { error: 'no_controller' };
  const scope = window.angular.element(el).scope();
  const opps = scope?.opportunities || [];
  return {
    opportunities: opps.map((o, index) => ({
      index,
      job_id: o?.job?.id,
      title: (o?.job?.title || '').trim(),
      company: (
        o?.job?.hiring_company_name ||
        o?.employer?.company_name ||
        o?.employer?.name ||
        ''
      ).trim(),
      opportunity_url: (o?.job?.opportunity_url || '').trim(),
      locations: Array.isArray(o?.job?.locations)
        ? o.job.locations
            .map((loc) => {
              if (typeof loc === 'string') return loc.trim();
              if (loc && typeof loc === 'object') {
                return String(loc.name || loc.city || loc.label || '').trim();
              }
              return '';
            })
            .filter(Boolean)
        : [],
    })),
  };
}
"""

_JOB_AVAILABLE_IN_RE = re.compile(
    r"^\s*(?:\d+\s+)?jobs?\s+available\s+in\s+(.+)$",
    re.IGNORECASE,
)

_POSTED_AT_SOURCE = "schema.org_job_posting"

_JOB_POSTING_LD_JS = """
() => {
  const blocks = [];
  document.querySelectorAll('script[type="application/ld+json"]').forEach((s) => {
    try {
      blocks.push(JSON.parse(s.textContent || ''));
    } catch (e) {}
  });
  for (const block of blocks) {
    if (block && block['@type'] === 'JobPosting' && block.datePosted) {
      return { datePosted: String(block.datePosted) };
    }
  }
  return null;
}
"""


@dataclass
class VisibleDomCard:
    index: int
    title: str
    company: str
    location: str
    card_text: str
    tags: list[str] = field(default_factory=list)


@dataclass
class AngularOpportunity:
    index: int
    job_id: str
    title: str
    company: str
    opportunity_url: str
    locations: list[str] = field(default_factory=list)


@dataclass
class OpportunityCard:
    job_id: str
    opportunity_url_path: str
    canonical_url: str
    title: str
    company: str
    location: str
    card_text: str
    tags: list[str] = field(default_factory=list)


def save_instahyre_session() -> None:
    """One-time manual login; persists storage_state to instahyre_auth.json."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto(f"{_ORIGIN}/login", timeout=60000, wait_until="domcontentloaded")
        print("👉 Log in to Instahyre manually, then press ENTER here")
        input()
        page.goto(_FEED_MATCHING_URL, timeout=60000, wait_until="domcontentloaded")
        page.wait_for_timeout(3000)
        _assert_candidate_session(page)
        context.storage_state(path=_AUTH_PATH)
        browser.close()
    print(f"Saved session to {_AUTH_PATH}")


def _new_authenticated_context(browser):
    if os.path.isfile(_AUTH_PATH):
        return browser.new_context(storage_state=_AUTH_PATH)
    context = browser.new_context()
    page = context.new_page()
    page.goto(f"{_ORIGIN}/login", timeout=60000, wait_until="domcontentloaded")
    print("👉 Instahyre session not found. Log in manually, then press ENTER")
    input()
    page.goto(_FEED_MATCHING_URL, timeout=60000, wait_until="domcontentloaded")
    page.wait_for_timeout(2000)
    context.storage_state(path=_AUTH_PATH)
    context.close()
    return browser.new_context(storage_state=_AUTH_PATH)


_CANDIDATE_SESSION_PATH_PREFIXES = (
    "/candidate/opportunities",
    "/search-jobs",
)
_RECRUITER_SESSION_PATH_MARKERS = (
    "/employer/",
    "/recruiters/",
    "/hiring/dashboard",
)


def is_valid_candidate_session_url(url: str) -> bool:
    """
    True when URL looks like an authenticated candidate surface (Feed 1 or Feed 2).
    """
    low = (url or "").strip().lower()
    if not low or "instahyre.com" not in low:
        return False
    if "/login" in low:
        return False
    if "sign" in low and not any(
        marker in low for marker in ("opportunities", "search-jobs", "/candidate/")
    ):
        return False
    if any(marker in low for marker in _RECRUITER_SESSION_PATH_MARKERS):
        return False
    if "/job-" in low:
        return True
    return any(prefix in low for prefix in _CANDIDATE_SESSION_PATH_PREFIXES)


def _assert_candidate_session(page: Page) -> None:
    url = page.url or ""
    low = url.lower()
    if is_valid_candidate_session_url(url):
        return
    if "/login" in low or (
        "sign" in low
        and "opportunities" not in low
        and "search-jobs" not in low
        and "/candidate/" not in low
    ):
        raise RuntimeError(
            "Instahyre session is not authenticated for candidate opportunities. "
            "Re-run save_instahyre_session() after logging in as a candidate."
        )
    raise RuntimeError(
        f"Unexpected Instahyre landing URL after auth: {url}. "
        "Expected candidate surfaces: /candidate/opportunities/, /search-jobs, or /job- detail."
    )


def _norm_label(value: str) -> str:
    s = re.sub(r"[^\w\s.-]", " ", (value or "").lower())
    return re.sub(r"\s+", " ", s).strip()


def _company_labels_align(dom_company: str, ang_company: str) -> bool:
    dc = _norm_label(dom_company)
    ac = _norm_label(ang_company)
    if not dc or not ac:
        return False
    if dc == ac:
        return True
    return dc in ac or ac in dc


def _title_labels_align(dom_title: str, ang_title: str) -> bool:
    dt = _norm_label(dom_title)
    at = _norm_label(ang_title)
    if not dt or not at:
        return False
    if dt == at:
        return True
    if dt in at or at in dt:
        return True
    dtoks = set(dt.split())
    atoks = set(at.split())
    if not dtoks or not atoks:
        return False
    overlap = len(dtoks & atoks) / max(len(dtoks), len(atoks))
    return overlap >= 0.7


def _dom_angular_align(dom: VisibleDomCard, ang: AngularOpportunity) -> bool:
    return _company_labels_align(dom.company, ang.company) and _title_labels_align(
        dom.title, ang.title
    )


def _alignment_score(dom: VisibleDomCard, ang: AngularOpportunity) -> int:
    score = 0
    if _company_labels_align(dom.company, ang.company):
        score += 2
    if _title_labels_align(dom.title, ang.title):
        score += 3
    if dom.index == ang.index:
        score += 1
    return score


def _parse_company_title_from_card(card_text: str) -> tuple[str, str]:
    lines = [ln.strip() for ln in (card_text or "").split("\n") if ln.strip()]
    if not lines:
        return "", ""

    header = lines[0]
    if " - " in header:
        company, title = header.split(" - ", 1)
        return company.strip(), title.strip()

    for ln in lines[:4]:
        if " - " in ln and len(ln) < 160:
            company, title = ln.split(" - ", 1)
            return company.strip(), title.strip()

    return "", ""


def _normalize_instahyre_location_line(raw: str) -> str:
    s = (raw or "").strip()
    if not s:
        return ""
    s = _JOB_AVAILABLE_IN_RE.sub(r"\1", s).strip()
    s = re.sub(r"^\d+\s+jobs?\s+available\s+in\s+", "", s, flags=re.IGNORECASE)
    s = re.sub(r"^jobs?\s+available\s+in\s+", "", s, flags=re.IGNORECASE)
    s = re.sub(r"^job\s+available\s+in\s+", "", s, flags=re.IGNORECASE)
    return " ".join(s.split())


def _looks_like_company_title_line(line: str) -> bool:
    if " - " not in line:
        return False
    left, _right = line.split(" - ", 1)
    return 0 < len(left.strip()) < 50


def _is_card_metadata_line(line: str) -> bool:
    low = line.lower()
    return any(
        token in low
        for token in (
            "founded in",
            "employees",
            "employee",
            "instamatch",
            "view »",
            "view interested",
            "not interested",
            "your chances",
        )
    )


def _join_location_parts(parts: list[str]) -> str:
    seen: list[str] = []
    for part in parts:
        for piece in part.split(","):
            loc = _normalize_instahyre_location_line(piece)
            if loc and loc not in seen:
                seen.append(loc)
    return ", ".join(seen)


def _parse_location_from_card(card_text: str) -> str:
    found: list[str] = []
    for ln in (card_text or "").split("\n"):
        ln = ln.strip()
        if not ln or _is_card_metadata_line(ln) or _looks_like_company_title_line(ln):
            continue
        m = _JOB_AVAILABLE_IN_RE.match(ln)
        if m:
            loc = _normalize_instahyre_location_line(m.group(1))
            if loc:
                found.append(loc)
    merged = _join_location_parts(found)
    return merged or "India"


def _merge_card_and_angular_locations(dom_location: str, angular_locations: list[str]) -> str:
    parts = [dom_location, *angular_locations]
    merged = _join_location_parts(parts)
    return merged or "India"


def uses_dom_first_harvest(feed_id: str) -> bool:
    """Feed 2 search-jobs: harvest from DOM job links without Angular alignment."""
    return str(feed_id or "").strip() == _FEED_ID_PM_CURATED_SEARCH


def _normalize_opportunity_href(href: str) -> str:
    raw = (href or "").strip()
    if not raw:
        return ""
    if raw.startswith("http://") or raw.startswith("https://"):
        path = urlparse(raw).path or ""
        return path if path.startswith("/") else f"/{path}"
    return raw if raw.startswith("/") else f"/{raw}"


def _opportunity_card_from_dom(
    dom: VisibleDomCard, opportunity_path: str
) -> OpportunityCard | None:
    """Build OpportunityCard from visible DOM row + validated /job- link."""
    path = _normalize_opportunity_href(opportunity_path)
    if not path:
        return None
    job_id, canonical_url = _canonical_url_from_opportunity_path(path)
    if not job_id or not canonical_url:
        return None
    rel_path = path.split("?", 1)[0]
    if not rel_path.endswith("/"):
        rel_path = rel_path.rstrip("/") + "/"
    return OpportunityCard(
        job_id=job_id,
        opportunity_url_path=rel_path,
        canonical_url=canonical_url,
        title=dom.title,
        company=dom.company,
        location=dom.location,
        card_text=dom.card_text,
        tags=dom.tags,
    )


def _canonical_url_from_opportunity_path(path: str) -> tuple[str | None, str | None]:
    """Validate Angular opportunity_url; return (job_id, absolute_url)."""
    path = (path or "").strip()
    if not path:
        return None, None
    if not path.startswith("/"):
        path = "/" + path
    m = _OPPORTUNITY_URL_RE.match(path)
    if not m:
        return None, None
    job_id = m.group(1)
    absolute = urljoin(_ORIGIN + "/", path.lstrip("/"))
    if not absolute.startswith(_ORIGIN):
        return None, None
    return job_id, absolute.rstrip("/") + "/"


def _feed_signal_count(page: Page) -> int:
    try:
        sig = page.evaluate(_FEED_SIGNAL_JS)
        return max(int(sig.get("employerBlocks", 0)), int(sig.get("interestedButtons", 0)))
    except Exception:
        return 0


def _parse_visible_dom_blocks(page: Page) -> list[VisibleDomCard]:
    try:
        raw_blocks = page.evaluate(_DOM_BLOCKS_JS)
    except Exception as e:
        log_debug(f"  [debug] instahyre_dom_blocks_error={e!r}")
        return []

    cards: list[VisibleDomCard] = []
    for entry in raw_blocks or []:
        card_text = str(entry.get("cardText") or "").strip()
        if len(card_text) < 40:
            continue
        company, title = _parse_company_title_from_card(card_text)
        if not title or not company:
            log_debug_rejection(
                "dom_card_header_missing",
                index=entry.get("index"),
                header=(card_text.split("\n", 1)[0] if card_text else ""),
            )
            continue
        cards.append(
            VisibleDomCard(
                index=int(entry.get("index", len(cards))),
                title=title,
                company=company,
                location=_parse_location_from_card(card_text),
                card_text=card_text,
                tags=[str(t) for t in (entry.get("tags") or []) if t],
            )
        )
    return cards


def _read_angular_opportunities(page: Page) -> list[AngularOpportunity]:
    try:
        payload = page.evaluate(_ANGULAR_OPPS_JS)
    except Exception as e:
        log_debug(f"  [debug] instahyre_angular_read_error={e!r}")
        return []

    if not isinstance(payload, dict):
        return []
    if payload.get("error"):
        log_debug(f"  [debug] instahyre_angular_read_error={payload.get('error')!r}")
        return []

    out: list[AngularOpportunity] = []
    for entry in payload.get("opportunities") or []:
        job_id = str(entry.get("job_id") or "").strip()
        opportunity_url = str(entry.get("opportunity_url") or "").strip()
        title = str(entry.get("title") or "").strip()
        company = str(entry.get("company") or "").strip()
        if not job_id or not opportunity_url or not title or not company:
            continue
        parsed_id, _ = _canonical_url_from_opportunity_path(opportunity_url)
        if not parsed_id or parsed_id != job_id:
            log_debug_rejection(
                "angular_opportunity_url_invalid",
                job_id=job_id,
                opportunity_url=opportunity_url,
            )
            continue
        locations = [
            str(loc).strip()
            for loc in (entry.get("locations") or [])
            if str(loc).strip()
        ]
        out.append(
            AngularOpportunity(
                index=int(entry.get("index", len(out))),
                job_id=job_id,
                title=title,
                company=company,
                opportunity_url=opportunity_url,
                locations=locations,
            )
        )
    return out


def _align_dom_with_angular(
    dom_cards: list[VisibleDomCard],
    angular_opps: list[AngularOpportunity],
) -> tuple[list[OpportunityCard], int]:
    """
    Pair visible DOM cards with Angular opportunities.
    Index is a hint only; rows must pass title/company alignment checks.
    """
    aligned: list[OpportunityCard] = []
    mismatches = 0
    used_angular: set[int] = set()

    for dom in dom_cards:
        candidates: list[tuple[int, AngularOpportunity]] = []

        if dom.index < len(angular_opps):
            hint = angular_opps[dom.index]
            if hint.index not in used_angular and _dom_angular_align(dom, hint):
                candidates.append((_alignment_score(dom, hint), hint))

        for ang in angular_opps:
            if ang.index in used_angular:
                continue
            if _dom_angular_align(dom, ang):
                candidates.append((_alignment_score(dom, ang), ang))

        if not candidates:
            mismatches += 1
            log_debug_rejection(
                "alignment_mismatch",
                dom_index=dom.index,
                dom_company=dom.company,
                dom_title=dom.title,
            )
            continue

        candidates.sort(key=lambda x: x[0], reverse=True)
        best_ang = candidates[0][1]
        used_angular.add(best_ang.index)

        job_id, canonical_url = _canonical_url_from_opportunity_path(best_ang.opportunity_url)
        if not job_id or not canonical_url:
            mismatches += 1
            log_debug_rejection(
                "alignment_mismatch",
                dom_index=dom.index,
                detail="invalid_opportunity_url_after_match",
                opportunity_url=best_ang.opportunity_url,
            )
            continue

        location = _merge_card_and_angular_locations(dom.location, best_ang.locations)

        aligned.append(
            OpportunityCard(
                job_id=job_id,
                opportunity_url_path=best_ang.opportunity_url,
                canonical_url=canonical_url,
                title=dom.title,
                company=dom.company,
                location=location,
                card_text=dom.card_text,
                tags=dom.tags,
            )
        )

    return aligned, mismatches


def _harvest_dom_first_cards(page: Page) -> tuple[list[OpportunityCard], dict[str, int]]:
    """Feed 2 (search-jobs): build OpportunityCards from DOM blocks + /job- links."""
    try:
        raw_blocks = page.evaluate(_DOM_BLOCKS_HARVEST_JS)
    except Exception as e:
        log_debug(f"  [debug] instahyre_dom_blocks_error={e!r}")
        raw_blocks = []

    aligned: list[OpportunityCard] = []
    dom_cards_rejected = 0
    valid_job_links_found = 0
    blocks_seen = 0

    for entry in raw_blocks or []:
        blocks_seen += 1
        card_text = str(entry.get("cardText") or "").strip()
        if len(card_text) < 40:
            dom_cards_rejected += 1
            continue
        company, title = _parse_company_title_from_card(card_text)
        if not title or not company:
            dom_cards_rejected += 1
            log_debug_rejection(
                "dom_card_header_missing",
                index=entry.get("index"),
                header=(card_text.split("\n", 1)[0] if card_text else ""),
            )
            continue

        opportunity_path = str(entry.get("opportunityPath") or "").strip()
        if opportunity_path:
            valid_job_links_found += 1
        dom = VisibleDomCard(
            index=int(entry.get("index", len(aligned))),
            title=title,
            company=company,
            location=_parse_location_from_card(card_text),
            card_text=card_text,
            tags=[str(t) for t in (entry.get("tags") or []) if t],
        )
        card = _opportunity_card_from_dom(dom, opportunity_path)
        if not card:
            dom_cards_rejected += 1
            log_debug_rejection(
                "dom_job_link_invalid",
                dom_index=dom.index,
                dom_company=dom.company,
                dom_title=dom.title,
                opportunity_path=opportunity_path,
            )
            continue
        aligned.append(card)

    stats = {
        "harvest_mode": "dom_first",
        "employer_blocks_visible": blocks_seen,
        "angular_opportunities_count": 0,
        "aligned_cards": len(aligned),
        "alignment_mismatches": 0,
        "dom_cards_harvested": len(aligned),
        "angular_alignment_used": 0,
        "dom_cards_rejected": dom_cards_rejected,
        "valid_job_links_found": valid_job_links_found,
    }
    return aligned, stats


def _harvest_aligned_cards(page: Page) -> tuple[list[OpportunityCard], dict[str, int]]:
    dom_cards = _parse_visible_dom_blocks(page)
    angular_opps = _read_angular_opportunities(page)
    aligned, mismatches = _align_dom_with_angular(dom_cards, angular_opps)
    stats = {
        "harvest_mode": "angular_aligned",
        "employer_blocks_visible": len(dom_cards),
        "angular_opportunities_count": len(angular_opps),
        "aligned_cards": len(aligned),
        "alignment_mismatches": mismatches,
        "dom_cards_harvested": len(aligned),
        "angular_alignment_used": 1 if angular_opps else 0,
        "dom_cards_rejected": mismatches,
        "valid_job_links_found": len(aligned),
    }
    return aligned, stats


def _harvest_feed_cards(
    page: Page, *, feed_id: str
) -> tuple[list[OpportunityCard], dict[str, int]]:
    if uses_dom_first_harvest(feed_id):
        return _harvest_dom_first_cards(page)
    return _harvest_aligned_cards(page)


_SCROLL_CONTAINER_LEGACY_JS = """
() => {
    const candidates = Array.from(document.querySelectorAll(
      '.candidate-opportunities, [class*="opportunit"], [class*="scroll"], [class*="list"]'
    ));
    let best = null;
    let bestScore = 0;
    for (const el of candidates) {
        const sh = el.scrollHeight;
        const ch = el.clientHeight;
        if (sh > ch + 80 && ch > 120) {
            const score = sh - ch;
            if (score > bestScore) { best = el; bestScore = score; }
        }
    }
    return best || document.scrollingElement || document.documentElement;
}
"""

_SCROLL_CONTAINER_DESCRIBE_JS = """
(el) => {
    if (!el) return 'none';
    const tag = el.tagName || '?';
    const id = el.id ? ('#' + el.id) : '';
    const cls = (el.className || '').toString().trim().split(/\\s+/).filter(Boolean).slice(0, 3).join('.');
    return tag + id + (cls ? '.' + cls : '');
}
"""

_DEEP_SCROLL_MARK_TARGET_JS = """
() => {
    const root = document.querySelector('.candidate-opportunities');
    const describe = (el) => {
        if (!el) return 'none';
        const tag = el.tagName || '?';
        const id = el.id ? ('#' + el.id) : '';
        const cls = (el.className || '').toString().trim().split(/\\s+/).filter(Boolean).slice(0, 3).join('.');
        return tag + id + (cls ? '.' + cls : '');
    };
    const isBanned = (el) => {
        if (!el) return true;
        const tag = (el.tagName || '').toUpperCase();
        return tag === 'HTML' || tag === 'BODY' || el === document.documentElement;
    };
    const metricsFor = (el) => {
        if (!el) {
            return {
                scrollTop: 0,
                scrollHeight: 0,
                clientHeight: 0,
                scrollable: false,
                employerBlocks: 0,
            };
        }
        const sh = el.scrollHeight || 0;
        const ch = el.clientHeight || 0;
        const st = el.scrollTop || 0;
        let overflowScroll = false;
        try {
            const oy = window.getComputedStyle(el).overflowY;
            overflowScroll = oy === 'auto' || oy === 'scroll' || oy === 'overlay';
        } catch (e) { /* ignore */ }
        return {
            scrollTop: st,
            scrollHeight: sh,
            clientHeight: ch,
            scrollable: (sh > ch + 8) || overflowScroll,
            employerBlocks: el.querySelectorAll('.employer-block').length,
        };
    };
    const scoreEl = (el) => {
        if (!el || isBanned(el)) return -1;
        if (!root) return -1;
        if (el !== root && !root.contains(el)) return -1;
        const m = metricsFor(el);
        let score = 0;
        if (el === root) score += 600;
        if (m.employerBlocks > 0) score += m.employerBlocks * 120;
        if (m.scrollable) score += Math.min(800, (m.scrollHeight - m.clientHeight) * 3);
        else if (el === root) score += 200;
        return score;
    };

    if (!root) {
        return {
            marked: false,
            descriptor: 'none',
            fallback_reason: 'no_candidate_opportunities_root',
            ineffective_scroll_target: true,
            is_document_fallback: false,
            scrollTop: 0,
            scrollHeight: 0,
            clientHeight: 0,
            scrollable: false,
            employerBlocks: 0,
        };
    }

    let best = root;
    let bestScore = scoreEl(root);
    for (const el of root.querySelectorAll('*')) {
        const s = scoreEl(el);
        if (s > bestScore) {
            best = el;
            bestScore = s;
        }
    }

    document.querySelectorAll('[data-instahyre-scroll-target]').forEach((el) => {
        if (el !== best) el.removeAttribute('data-instahyre-scroll-target');
    });
    best.setAttribute('data-instahyre-scroll-target', '1');

    const m = metricsFor(best);
    const descriptor = describe(best);
    const isDocumentFallback = isBanned(best);
    const ineffective =
        isDocumentFallback || (!m.scrollable && best !== root);

    return {
        marked: true,
        descriptor,
        fallback_reason: isDocumentFallback ? 'document_element_banned' : '',
        ineffective_scroll_target: ineffective,
        is_document_fallback: isDocumentFallback,
        scrollTop: m.scrollTop,
        scrollHeight: m.scrollHeight,
        clientHeight: m.clientHeight,
        scrollable: m.scrollable,
        employerBlocks: m.employerBlocks,
    };
}
"""

_DEEP_SCROLL_MARKED_ELEMENT_JS = """
(args) => {
    const step = args.step || 700;
    const el = document.querySelector('[data-instahyre-scroll-target="1"]');
    if (!el) {
        return {
            moved: false,
            scrollTopBefore: 0,
            scrollTopAfter: 0,
            scrollHeight: 0,
            clientHeight: 0,
            fallback_reason: 'no_marked_scroll_target',
        };
    }
    const maxTop = Math.max(0, el.scrollHeight - el.clientHeight);
    const before = el.scrollTop || 0;
    el.scrollTop = Math.min(before + step, maxTop);
    const after = el.scrollTop || 0;
    return {
        moved: after > before || (after >= maxTop && maxTop > 0),
        scrollTopBefore: before,
        scrollTopAfter: after,
        scrollHeight: el.scrollHeight || 0,
        clientHeight: el.clientHeight || 0,
        fallback_reason: '',
    };
}
"""

_DEEP_SCROLL_LAST_BLOCK_JS = """
() => {
    const root = document.querySelector('.candidate-opportunities');
    if (!root) {
        return { moved: false, fallback_reason: 'no_candidate_opportunities_root' };
    }
    const blocks = root.querySelectorAll('.employer-block');
    if (!blocks.length) {
        return { moved: false, fallback_reason: 'no_employer_blocks' };
    }
    const last = blocks[blocks.length - 1];
    const beforeTop = root.scrollTop || 0;
    last.scrollIntoView({ block: 'end', inline: 'nearest', behavior: 'instant' });
    const afterTop = root.scrollTop || 0;
    return {
        moved: true,
        fallback_reason: '',
        blockCount: blocks.length,
        scrollTopBefore: beforeTop,
        scrollTopAfter: afterTop,
    };
}
"""


def _wait_for_feed_cards_stable(page: Page, list_wait_ms: int) -> str:
    deadline = time.monotonic() + (list_wait_ms / 1000.0)
    stable_rounds = 0
    last_count = -1

    while time.monotonic() < deadline:
        count = _feed_signal_count(page)
        if count > 0:
            if count == last_count:
                stable_rounds += 1
                if stable_rounds >= 2:
                    return "cards_stable"
            else:
                stable_rounds = 0
            last_count = count
        page.wait_for_timeout(1200)

    if last_count > 0:
        return "cards_timeout_partial"
    return "cards_timeout_empty"


def _debug_dom_snapshot(page: Page, label: str, *, feed_id: str) -> None:
    """Debug-only DOM screenshot + feed-signal probe (does not affect acquisition)."""
    if not debug_dom_enabled():
        return
    try:
        os.makedirs("logs", exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        shot = str(paths.instahyre_debug_screenshot(f"instahyre-debug-{label}-{ts}.png"))
        page.screenshot(path=shot, full_page=True)
        log_debug(f"    [debug] screenshot={shot}")
        stats = page.evaluate(_FEED_SIGNAL_JS)
        log_debug(f"    [debug] feed_signals={stats}")
        _, harvest_stats = _harvest_feed_cards(page, feed_id=feed_id)
        log_debug(
            f"    [debug] debug_harvest_probe feed_id={feed_id!r} "
            f"harvest_mode={harvest_stats.get('harvest_mode')!r} "
            f"stats={harvest_stats}"
        )
    except Exception as e:
        log_debug(f"    [debug] snapshot_failed={e!r}")


def _find_scroll_container(
    page: Page, *, deep_discovery: bool
) -> tuple[Any | None, str]:
    try:
        if deep_discovery:
            probe = _probe_deep_scroll_target(page)
            locator = page.locator('[data-instahyre-scroll-target="1"]')
            if locator.count() > 0:
                return locator.first.element_handle(), str(probe.get("descriptor", ""))
            return None, str(probe.get("descriptor", "unmarked"))
        handle = page.evaluate_handle(_SCROLL_CONTAINER_LEGACY_JS)
        return handle.as_element(), "legacy_heuristic"
    except Exception:
        return None, "error"


def _probe_deep_scroll_target(page: Page) -> dict[str, Any]:
    try:
        payload = page.evaluate(_DEEP_SCROLL_MARK_TARGET_JS)
        if isinstance(payload, dict):
            return payload
    except Exception as exc:
        return {
            "marked": False,
            "descriptor": "probe_error",
            "fallback_reason": repr(exc),
            "ineffective_scroll_target": True,
            "is_document_fallback": False,
        }
    return {
        "marked": False,
        "descriptor": "probe_invalid",
        "fallback_reason": "invalid_probe_payload",
        "ineffective_scroll_target": True,
        "is_document_fallback": False,
    }


def _deep_scroll_step_size(page: Page) -> int:
    locator = page.locator('[data-instahyre-scroll-target="1"]')
    if locator.count() == 0:
        return 700
    try:
        return int(
            locator.first.evaluate(
                "(el) => Math.max(320, Math.floor((el.clientHeight || 700) * 0.85))"
            )
            or 700
        )
    except Exception:
        return 700


def _strategy_container_scroll(page: Page, step: int) -> dict[str, Any]:
    probe = _probe_deep_scroll_target(page)
    result: dict[str, Any] = {
        "scroll_strategy_used": "container_scroll",
        "scroll_container_selected": probe.get("descriptor", ""),
        "ineffective_scroll_target": bool(probe.get("ineffective_scroll_target")),
        "fallback_reason": str(probe.get("fallback_reason") or ""),
        "is_document_fallback": bool(probe.get("is_document_fallback")),
    }
    try:
        scroll_result = page.evaluate(_DEEP_SCROLL_MARKED_ELEMENT_JS, {"step": step})
        if isinstance(scroll_result, dict):
            result.update(scroll_result)
            result["scroll_moved"] = bool(scroll_result.get("moved"))
        else:
            result["scroll_moved"] = False
            result["fallback_reason"] = result.get("fallback_reason") or "invalid_scroll_result"
    except Exception as exc:
        result["scroll_moved"] = False
        result["fallback_reason"] = f"container_scroll_error:{exc!r}"
    if not result.get("scroll_moved") and not result.get("fallback_reason"):
        result["fallback_reason"] = "scroll_top_unchanged_or_non_scrollable"
    return result


def _strategy_scroll_last_block(page: Page) -> dict[str, Any]:
    result: dict[str, Any] = {"scroll_strategy_used": "scroll_into_view_last_block"}
    try:
        payload = page.evaluate(_DEEP_SCROLL_LAST_BLOCK_JS)
        if isinstance(payload, dict):
            result.update(payload)
            result["scroll_moved"] = bool(payload.get("moved"))
            if not result.get("fallback_reason"):
                result["fallback_reason"] = ""
        else:
            result["scroll_moved"] = False
            result["fallback_reason"] = "invalid_scroll_into_view_result"
    except Exception as exc:
        result["scroll_moved"] = False
        result["fallback_reason"] = f"scroll_into_view_error:{exc!r}"
    return result


def _strategy_focus_page_down(page: Page) -> dict[str, Any]:
    result: dict[str, Any] = {
        "scroll_strategy_used": "focus_opportunities_page_down",
        "scroll_moved": False,
        "fallback_reason": "",
    }
    try:
        root = page.locator(".candidate-opportunities").first
        if root.count() == 0:
            result["fallback_reason"] = "no_candidate_opportunities_root"
            return result
        root.focus()
        page.wait_for_timeout(150)
        page.keyboard.press("PageDown")
        result["scroll_moved"] = True
    except Exception as exc:
        result["fallback_reason"] = f"page_down_error:{exc!r}"
    return result


def _strategy_wheel_on_opportunities(page: Page, step: int) -> dict[str, Any]:
    result: dict[str, Any] = {
        "scroll_strategy_used": "wheel_on_opportunities_bbox",
        "scroll_moved": False,
        "fallback_reason": "",
    }
    try:
        root = page.locator(".candidate-opportunities").first
        if root.count() == 0:
            result["fallback_reason"] = "no_candidate_opportunities_root"
            return result
        box = root.bounding_box()
        if not box:
            result["fallback_reason"] = "no_bounding_box"
            return result
        x = box["x"] + box["width"] / 2
        y = box["y"] + min(box["height"] * 0.85, box["height"] - 8)
        page.mouse.move(x, y)
        page.mouse.wheel(0, step)
        result["scroll_moved"] = True
    except Exception as exc:
        result["fallback_reason"] = f"wheel_bbox_error:{exc!r}"
    return result


def _strategy_document_wheel_last_resort(page: Page, step: int) -> dict[str, Any]:
    """Only when opportunities root exists but inner strategies failed."""
    result: dict[str, Any] = {
        "scroll_strategy_used": "document_wheel_last_resort",
        "scroll_moved": False,
        "fallback_reason": "last_resort_document_wheel",
        "is_document_fallback": True,
    }
    try:
        if page.locator(".candidate-opportunities").count() == 0:
            result["fallback_reason"] = "skipped_no_opportunities_root"
            return result
        page.mouse.wheel(0, step)
        result["scroll_moved"] = True
    except Exception as exc:
        result["fallback_reason"] = f"document_wheel_error:{exc!r}"
    return result


def _run_deep_scroll_strategy_chain(
    page: Page,
    *,
    step: int,
    post_scroll_wait_ms: int,
    merged: dict[str, OpportunityCard],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """
    Try scroll strategies in order until DOM/merged growth or chain exhausted.
    Returns cycle summary and per-strategy attempt logs.
    """
    signal_before_cycle = _feed_signal_count(page)
    merged_before_cycle = len(merged)
    attempts: list[dict[str, Any]] = []

    strategies: list[tuple[str, Any]] = [
        ("container_scroll", lambda: _strategy_container_scroll(page, step)),
        ("scroll_into_view_last_block", lambda: _strategy_scroll_last_block(page)),
        ("focus_opportunities_page_down", lambda: _strategy_focus_page_down(page)),
        ("wheel_on_opportunities_bbox", lambda: _strategy_wheel_on_opportunities(page, step)),
        ("document_wheel_last_resort", lambda: _strategy_document_wheel_last_resort(page, step)),
    ]

    cycle_summary: dict[str, Any] = {
        "scroll_strategy_used": "none",
        "scroll_moved": False,
        "ineffective_scroll_target": False,
        "fallback_reason": "",
        "feed_signal_before": signal_before_cycle,
        "feed_signal_after": signal_before_cycle,
        "strategy_chain_exhausted": True,
    }
    any_scroll_moved = False

    for _name, run_strategy in strategies:
        attempt = run_strategy()
        signal_before_strategy = _feed_signal_count(page)
        merged_before_strategy = len(merged)

        signal_grew, signal_after = _wait_after_scroll_for_growth(
            page,
            post_scroll_wait_ms=post_scroll_wait_ms,
            baseline_signal=signal_before_strategy,
        )

        aligned, stats = _harvest_aligned_cards(page)
        for card in aligned:
            merged[card.job_id] = card

        merged_after = len(merged)
        merged_delta = merged_after - merged_before_strategy
        dom_grew = signal_grew or merged_delta > 0
        any_scroll_moved = any_scroll_moved or bool(attempt.get("scroll_moved"))

        attempt["feed_signal_before"] = signal_before_strategy
        attempt["feed_signal_after"] = signal_after
        attempt["dom_signal_grew"] = signal_grew
        attempt["merged_after_strategy"] = merged_after
        attempt["merged_delta_strategy"] = merged_delta
        attempt["employer_blocks_visible"] = stats.get("employer_blocks_visible", 0)
        attempt["angular_opportunities_count"] = stats.get("angular_opportunities_count", 0)
        attempt["aligned_cards"] = stats.get("aligned_cards", 0)
        attempt["alignment_mismatches"] = stats.get("alignment_mismatches", 0)
        attempt["dom_grew"] = dom_grew
        attempts.append(attempt)

        if dom_grew:
            cycle_summary["scroll_strategy_used"] = attempt.get(
                "scroll_strategy_used", "unknown"
            )
            cycle_summary["ineffective_scroll_target"] = bool(
                attempt.get("ineffective_scroll_target")
            )
            cycle_summary["fallback_reason"] = str(attempt.get("fallback_reason") or "")
            cycle_summary["feed_signal_after"] = signal_after
            cycle_summary["strategy_chain_exhausted"] = False
            break

    cycle_summary["scroll_moved"] = any_scroll_moved

    if cycle_summary.get("scroll_strategy_used") in ("none", "", None):
        if attempts:
            last = attempts[-1]
            cycle_summary["scroll_strategy_used"] = last.get(
                "scroll_strategy_used", "chain_exhausted"
            )
            cycle_summary["ineffective_scroll_target"] = bool(
                last.get("ineffective_scroll_target")
            )
            cycle_summary["fallback_reason"] = str(
                last.get("fallback_reason") or "all_strategies_ineffective"
            )
        cycle_summary["feed_signal_after"] = _feed_signal_count(page)

    cycle_summary["merged_delta"] = len(merged) - merged_before_cycle
    cycle_summary["strategy_attempts"] = len(attempts)
    return cycle_summary, attempts


def _scroll_container_step(scroll_el, step_px: int) -> bool:
    if scroll_el is None:
        return False
    try:
        return bool(
            scroll_el.evaluate(
                """(el, step) => {
                    const maxTop = Math.max(0, el.scrollHeight - el.clientHeight);
                    const before = el.scrollTop;
                    el.scrollTop = Math.min(el.scrollTop + step, maxTop);
                    return el.scrollTop > before || el.scrollTop >= maxTop;
                }""",
                step_px,
            )
        )
    except Exception:
        return False


def _wait_after_scroll_for_growth(
    page: Page,
    *,
    post_scroll_wait_ms: int,
    baseline_signal: int,
    poll_ms: int = 400,
) -> tuple[bool, int]:
    """Poll list signals after scroll so lazy-loaded cards can appear."""
    if post_scroll_wait_ms <= 0:
        return False, baseline_signal

    deadline = time.monotonic() + (post_scroll_wait_ms / 1000.0)
    peak_signal = baseline_signal
    grew = False
    while time.monotonic() < deadline:
        page.wait_for_timeout(poll_ms)
        count = _feed_signal_count(page)
        if count > peak_signal:
            peak_signal = count
            grew = True
    return grew, peak_signal


_PAGINATION_STATE_JS = """
() => {
  const oppRoot =
    document.querySelector('[ng-controller="candidateOpportunityCtrl"]') ||
    document.querySelector('.candidate-opportunities') ||
    document.querySelector('main') ||
    document.body;
  const scope =
    oppRoot && window.angular
      ? (() => {
          try {
            return window.angular.element(oppRoot).scope();
          } catch (e) {
            return null;
          }
        })()
      : null;
  const pag =
    oppRoot.querySelector('.pagination') ||
    document.querySelector('[ng-controller="candidateOpportunityCtrl"] .pagination') ||
    document.querySelector('.candidate-opportunities .pagination') ||
    document.querySelector('.pagination');
  if (!pag) {
    return {
      pagination_present: false,
      current_page: null,
      total_pages: null,
      page_numbers: [],
      next_available: false,
      has_next: false,
      target_page: null,
      pagination_inconsistency: false,
      raw_pagination_items: [],
      opportunities_signature: '',
    };
  }
  const normalizeBool = (raw) => {
    const s = String(raw || '').trim().toLowerCase();
    return s === '1' || s === 'true' || s === 'yes' || s === 'on';
  };
  const isDisabled = (el, ngDisabled) => {
    const ariaDisabled = String(el.getAttribute('aria-disabled') || '').trim().toLowerCase();
    const disabledAttr = el.hasAttribute('disabled');
    const disabledCls =
      el.classList.contains('disabled') ||
      el.classList.contains('is-disabled') ||
      el.classList.contains('btn-disabled');
    const hidden =
      el.classList.contains('hidden') ||
      el.classList.contains('ng-hide') ||
      String(el.getAttribute('aria-hidden') || '').trim().toLowerCase() === 'true';
    return hidden || disabledAttr || disabledCls || normalizeBool(ngDisabled) || ariaDisabled === 'true';
  };
  const items = Array.from(pag.querySelectorAll('li,button,a,[role="button"]'));
  const pageNumbers = [];
  const rawItems = [];
  let currentPage = null;
  let nextControlEnabled = false;
  for (const el of items) {
    const text = (el.innerText || el.textContent || '').trim().replace(/\\s+/g, ' ');
    const ariaLabel = (el.getAttribute('aria-label') || '').trim();
    const ngClick = (el.getAttribute('ng-click') || '').trim();
    const ngDisabled = (el.getAttribute('ng-disabled') || '').trim();
    const classes = (el.className || '').toString();
    const disabled = isDisabled(el, ngDisabled);
    const isNumeric = /^\\d+$/.test(text);
    const isActive = el.classList.contains('active') || String(el.getAttribute('aria-current') || '') === 'page';
    const looksNext =
      /nextpage\\s*\\(/i.test(ngClick) ||
      /\\bnext\\b/i.test(text) ||
      /\\bnext\\b/i.test(ariaLabel) ||
      text === '>' ||
      text === '»';
    if (isNumeric) pageNumbers.push(Number(text));
    if (isActive && isNumeric) currentPage = Number(text);
    if (looksNext && !disabled) nextControlEnabled = true;
    rawItems.push({
      tag: el.tagName,
      text: text.slice(0, 40),
      aria_label: ariaLabel.slice(0, 60),
      ng_click: ngClick.slice(0, 80),
      ng_disabled: ngDisabled.slice(0, 80),
      disabled,
      active: isActive,
      classes: classes.slice(0, 120),
    });
  }
  const totalPages = pageNumbers.length ? Math.max(...pageNumbers) : null;
  const modelHasNext =
    Number.isFinite(currentPage) &&
    Number.isFinite(totalPages) &&
    Number(currentPage) < Number(totalPages);
  const hasNext = modelHasNext || nextControlEnabled;
  const targetPage = modelHasNext ? Number(currentPage) + 1 : null;
  const paginationInconsistency = modelHasNext && !nextControlEnabled;
  const opps = Array.isArray(scope?.opportunities) ? scope.opportunities : [];
  const signature = opps
    .slice(0, 3)
    .map((o) => String(o?.job?.id || ''))
    .filter(Boolean)
    .join('|');
  return {
    pagination_present: true,
    current_page: currentPage,
    total_pages: totalPages,
    page_numbers: pageNumbers,
    next_available: nextControlEnabled,
    has_next: hasNext,
    target_page: targetPage,
    pagination_inconsistency: paginationInconsistency,
    raw_pagination_items: rawItems.slice(0, 25),
    opportunities_signature: signature,
  };
}
"""

_PAGE_FIRST_JOB_ID_JS = """
() => {
  try {
    if (window.angular) {
      const el = document.querySelector('[ng-controller="candidateOpportunityCtrl"]');
      if (el) {
        const scope = window.angular.element(el).scope();
        const opps = scope?.opportunities || [];
        const first = opps[0]?.job?.id;
        if (first != null && String(first).trim()) return String(first).trim();
      }
    }
  } catch (e) {}
  const link = document.querySelector(
    '.candidate-opportunities .employer-block a[href*="/job-"]'
  );
  if (!link) return null;
  const href = link.getAttribute('href') || '';
  const m = href.match(/\\/job-(\\d+)/i);
  return m ? m[1] : null;
}
"""

_CLICK_PAGINATION_TARGET_JS = """
(targetPage) => {
  const oppRoot =
    document.querySelector('[ng-controller="candidateOpportunityCtrl"]') ||
    document.querySelector('.candidate-opportunities') ||
    document.querySelector('main') ||
    document.body;
  const pag =
    oppRoot.querySelector('.pagination') ||
    document.querySelector('[ng-controller="candidateOpportunityCtrl"] .pagination') ||
    document.querySelector('.candidate-opportunities .pagination') ||
    document.querySelector('.pagination');
  if (!pag) return { ok: false, reason: 'no_pagination' };
  const norm = (s) => (String(s || '').trim().toLowerCase());
  const isDisabled = (el) => {
    const ngDisabled = norm(el.getAttribute('ng-disabled'));
    const ariaDisabled = norm(el.getAttribute('aria-disabled'));
    return (
      el.hasAttribute('disabled') ||
      el.classList.contains('disabled') ||
      el.classList.contains('is-disabled') ||
      el.classList.contains('hidden') ||
      el.classList.contains('ng-hide') ||
      ariaDisabled === 'true' ||
      ngDisabled === 'true' ||
      ngDisabled === '1'
    );
  };

  if (targetPage != null) {
    const target = String(targetPage);
    const direct = Array.from(pag.querySelectorAll('li,a,button,[role="button"]')).find((el) => {
      const text = (el.innerText || el.textContent || '').trim();
      const ngClick = String(el.getAttribute('ng-click') || '');
      return (
        text === target ||
        new RegExp(`nthPage\\\\s*\\\\(\\\\s*${target}\\\\s*\\\\)`, 'i').test(ngClick)
      );
    });
    if (direct && !isDisabled(direct)) {
      const clickable = direct.querySelector('a,button,[role="button"]') || direct;
      clickable.click();
      return { ok: true, method: 'target_page_click', target_page: targetPage };
    }
  }

  const nextEl = Array.from(pag.querySelectorAll('li,a,button,[role="button"]')).find((el) => {
    const text = (el.innerText || el.textContent || '').trim();
    const ariaLabel = String(el.getAttribute('aria-label') || '');
    const ngClick = String(el.getAttribute('ng-click') || '');
    const looksNext =
      /nextpage\\s*\\(/i.test(ngClick) ||
      /\\bnext\\b/i.test(text) ||
      /\\bnext\\b/i.test(ariaLabel) ||
      text === '>' ||
      text === '»';
    return looksNext && !isDisabled(el);
  });
  if (!nextEl) return { ok: false, reason: 'next_not_available' };
  const clickable = nextEl.querySelector('a,button,[role="button"]') || nextEl;
  clickable.click();
  return { ok: true, method: 'next_control_click', target_page: null };
}
"""


def _read_pagination_state(page: Page) -> dict[str, Any]:
    try:
        raw = page.evaluate(_PAGINATION_STATE_JS)
        return dict(raw or {})
    except Exception:
        return {
            "pagination_present": False,
            "current_page": None,
            "total_pages": None,
            "next_available": False,
            "has_next": False,
            "target_page": None,
            "pagination_inconsistency": False,
            "raw_pagination_items": [],
            "opportunities_signature": "",
            "page_numbers": [],
        }


def _read_page_first_job_id(page: Page) -> str | None:
    try:
        raw = page.evaluate(_PAGE_FIRST_JOB_ID_JS)
        if raw:
            return str(raw).strip()
    except Exception:
        pass
    return None


def _go_to_next_page(
    page: Page, *, target_page: int | None = None
) -> tuple[bool, str, int | None]:
    if target_page is not None:
        try:
            target = page.locator(".pagination li, .pagination a, .pagination button").filter(
                has_text=re.compile(rf"^\s*{target_page}\s*$")
            )
            if target.count() > 0:
                el = target.first
                if el.is_visible() and not (
                    el.get_attribute("aria-disabled") == "true"
                    or "disabled" in str(el.get_attribute("class") or "")
                ):
                    el.click()
                    return True, "target_page_playwright_click", target_page
        except Exception:
            pass
    try:
        result = page.evaluate(_CLICK_PAGINATION_TARGET_JS, target_page)
        if isinstance(result, dict) and result.get("ok"):
            target_clicked = result.get("target_page")
            target_int = int(target_clicked) if target_clicked is not None else None
            return True, str(result.get("method") or "js_click"), target_int
        reason = "click_failed"
        if isinstance(result, dict):
            reason = str(result.get("reason") or reason)
        return False, reason, None
    except Exception as exc:
        return False, f"exception:{exc}", None


def _wait_for_page_transition(
    page: Page,
    *,
    before_page: Any,
    before_first_job_id: str | None,
    before_signature: str | None,
    timeout_ms: int,
) -> tuple[bool, str, dict[str, Any]]:
    deadline = time.monotonic() + (timeout_ms / 1000.0)
    poll_ms = 400
    last_diag: dict[str, Any] = {
        "before_page": before_page,
        "before_first_job_id": before_first_job_id,
        "before_signature": before_signature,
        "last_page": before_page,
        "last_first_job_id": before_first_job_id,
        "last_signature": before_signature,
    }
    while time.monotonic() < deadline:
        page.wait_for_timeout(poll_ms)
        state = _read_pagination_state(page)
        current = state.get("current_page")
        first_id = _read_page_first_job_id(page)
        signature = str(state.get("opportunities_signature") or "").strip()
        last_diag["last_page"] = current
        last_diag["last_first_job_id"] = first_id
        last_diag["last_signature"] = signature
        if before_page is not None and current is not None and current != before_page:
            return True, "active_page_changed", last_diag
        if before_first_job_id and first_id and first_id != before_first_job_id:
            return True, "first_job_id_changed", last_diag
        if before_signature and signature and signature != before_signature:
            return True, "opportunity_signature_changed", last_diag
    return False, "transition_timeout", last_diag


def _collect_feed_opportunity_cards_paginated(
    page: Page, settings: FeedDiscoverySettings
) -> tuple[list[OpportunityCard], dict[str, Any]]:
    """Paginated feeds: harvest cards page-by-page, then return merged set for detail extraction."""
    metrics: dict[str, Any] = {
        "feed_id": settings.feed_id,
        "harvest_mode": "dom_first" if uses_dom_first_harvest(settings.feed_id) else "angular_aligned",
        "deep_discovery_enabled": True,
        "traversal_mode": "pagination",
        "instahyre_wait_reason": "unknown",
        "pages_traversed": 0,
        "current_page": None,
        "total_pages": None,
        "next_available": False,
        "cards_per_page": [],
        "cumulative_unique_job_ids": 0,
        "pagination_inconsistency": False,
        "pagination_stop_reason": "max_pages",
        "page_traversal_details": [],
        "scroll_cycles": 0,
        "cards_after_stabilization": 0,
    }
    harvest_stats: dict[str, Any] = {
        "harvest_mode": metrics["harvest_mode"],
        "employer_blocks_visible": 0,
        "angular_opportunities_count": 0,
        "aligned_cards": 0,
        "alignment_mismatches": 0,
        "dom_cards_harvested": 0,
        "angular_alignment_used": 0,
        "dom_cards_rejected": 0,
        "valid_job_links_found": 0,
    }

    metrics["instahyre_wait_reason"] = _wait_for_feed_cards_stable(
        page, settings.list_wait_ms
    )
    page.wait_for_timeout(settings.initial_settle_ms)
    _debug_dom_snapshot(page, "post-wait-pagination", feed_id=settings.feed_id)

    merged: dict[str, OpportunityCard] = {}
    stop_reason = "max_pages"

    for page_num in range(1, settings.max_pages + 1):
        pag_state = _read_pagination_state(page)
        first_job_id = _read_page_first_job_id(page)
        current_page = pag_state.get("current_page")
        total_pages = pag_state.get("total_pages")
        next_available = bool(pag_state.get("next_available"))
        has_next = bool(pag_state.get("has_next"))
        target_page = pag_state.get("target_page")
        pagination_inconsistency = bool(pag_state.get("pagination_inconsistency"))
        raw_items = pag_state.get("raw_pagination_items") or []
        page_signature = str(pag_state.get("opportunities_signature") or "").strip()

        aligned, stats = _harvest_feed_cards(page, feed_id=settings.feed_id)
        for k, v in stats.items():
            if k == "harvest_mode":
                harvest_stats[k] = v
                metrics["harvest_mode"] = v
                continue
            if isinstance(v, (int, float)):
                harvest_stats[k] = max(int(harvest_stats.get(k, 0)), int(v))
            else:
                harvest_stats[k] = v

        new_on_page = 0
        for card in aligned:
            if card.job_id not in merged:
                new_on_page += 1
            merged[card.job_id] = card

        page_card_count = len(aligned)
        cumulative = len(merged)
        new_ratio = (new_on_page / page_card_count) if page_card_count else 0.0

        metrics["pages_traversed"] = page_num
        metrics["current_page"] = current_page
        metrics["total_pages"] = total_pages
        metrics["next_available"] = next_available
        metrics["pagination_inconsistency"] = pagination_inconsistency
        metrics["cards_per_page"].append(page_card_count)
        metrics["cumulative_unique_job_ids"] = cumulative

        page_detail: dict[str, Any] = {
            "page_num": page_num,
            "current_page": current_page,
            "total_pages": total_pages,
            "next_available": next_available,
            "has_next": has_next,
            "target_page": target_page,
            "pagination_inconsistency": pagination_inconsistency,
            "cards_on_page": page_card_count,
            "new_job_ids_on_page": new_on_page,
            "new_job_ratio": round(new_ratio, 4),
            "cumulative_unique_job_ids": cumulative,
            "first_job_id": first_job_id,
            "opportunities_signature": page_signature,
            "pagination_present": pag_state.get("pagination_present"),
            "raw_pagination_items": raw_items,
        }
        metrics["page_traversal_details"].append(page_detail)

        if page_num > 1 and page_card_count > 0:
            if new_ratio < settings.page_min_new_ratio:
                stop_reason = "saturation"
                metrics["pagination_stop_reason"] = stop_reason
                break

        if not has_next:
            stop_reason = "no_next"
            metrics["pagination_stop_reason"] = stop_reason
            break

        if page_num >= settings.max_pages:
            stop_reason = "max_pages"
            metrics["pagination_stop_reason"] = stop_reason
            break

        clicked, click_method, target_clicked = _go_to_next_page(
            page,
            target_page=target_page if isinstance(target_page, int) else None,
        )
        page_detail["next_click_method"] = click_method
        page_detail["target_page_clicked"] = target_clicked
        if not clicked:
            stop_reason = "next_click_failed"
            metrics["pagination_stop_reason"] = stop_reason
            break

        transitioned, transition_reason, transition_diag = _wait_for_page_transition(
            page,
            before_page=current_page,
            before_first_job_id=first_job_id,
            before_signature=page_signature,
            timeout_ms=settings.page_transition_wait_ms,
        )
        page_detail["page_transition"] = transition_reason
        page_detail["page_transition_diag"] = transition_diag
        if not transitioned:
            stop_reason = "transition_failed"
            metrics["pagination_stop_reason"] = stop_reason
            break

        page.wait_for_timeout(settings.page_settle_ms)

    if "pagination_stop_reason" not in metrics or metrics["pagination_stop_reason"] == "max_pages":
        metrics["pagination_stop_reason"] = stop_reason

    metrics.update(harvest_stats)
    metrics["cards_after_stabilization"] = len(merged)
    return list(merged.values()), metrics


def _collect_feed_opportunity_cards_legacy(
    page: Page, settings: FeedDiscoverySettings
) -> tuple[list[OpportunityCard], dict[str, Any]]:
    """Pre-deep-discovery list harvest (Feed 2 and non-matching feeds)."""
    metrics: dict[str, Any] = {
        "feed_id": settings.feed_id,
        "deep_discovery_enabled": False,
        "instahyre_wait_reason": "unknown",
        "scroll_cycles": 0,
        "cards_after_stabilization": 0,
    }

    metrics["instahyre_wait_reason"] = _wait_for_feed_cards_stable(
        page, settings.list_wait_ms
    )
    page.wait_for_timeout(settings.initial_settle_ms)
    _debug_dom_snapshot(page, "post-wait", feed_id=settings.feed_id)

    merged: dict[str, OpportunityCard] = {}
    harvest_stats = {
        "employer_blocks_visible": 0,
        "angular_opportunities_count": 0,
        "aligned_cards": 0,
        "alignment_mismatches": 0,
    }

    aligned, stats = _harvest_aligned_cards(page)
    for k, v in stats.items():
        harvest_stats[k] = max(harvest_stats.get(k, 0), v)
    for card in aligned:
        merged[card.job_id] = card

    scroll_el, _ = _find_scroll_container(page, deep_discovery=False)
    stable_rounds = 0
    last_total = len(merged)

    for cycle in range(settings.scroll_max_cycles):
        metrics["scroll_cycles"] = cycle + 1
        step = 700
        try:
            if scroll_el:
                step = int(
                    scroll_el.evaluate(
                        "(el) => Math.max(320, Math.floor(el.clientHeight * 0.85))"
                    )
                    or 700
                )
        except Exception:
            pass

        moved = _scroll_container_step(scroll_el, step)
        if not moved:
            page.mouse.wheel(0, step)
        page.wait_for_timeout(settings.post_scroll_wait_ms)

        aligned, stats = _harvest_aligned_cards(page)
        for k, v in stats.items():
            harvest_stats[k] = max(harvest_stats.get(k, 0), v)
        for card in aligned:
            merged[card.job_id] = card

        if len(merged) == last_total:
            stable_rounds += 1
        else:
            stable_rounds = 0
        last_total = len(merged)

        if stable_rounds >= settings.stable_rounds:
            break

    metrics.update(harvest_stats)
    metrics["cards_after_stabilization"] = len(merged)
    return list(merged.values()), metrics


def _collect_feed_opportunity_cards_deep(
    page: Page, settings: FeedDiscoverySettings
) -> tuple[list[OpportunityCard], dict[str, Any]]:
    """Feed 1 scroll fallback when INSTAHYRE_MATCHING_SCROLL_FALLBACK=1."""
    metrics: dict[str, Any] = {
        "traversal_mode": "scroll",
        "feed_id": settings.feed_id,
        "deep_discovery_enabled": True,
        "instahyre_wait_reason": "unknown",
        "stabilization_reason": "unknown",
        "scroll_container_selected": "pending",
        "scroll_cycles": 0,
        "cards_after_stabilization": 0,
        "cards_after_each_scroll": [],
        "scroll_cycle_details": [],
        "strategy_fallback_chains": [],
        "ineffective_scroll_cycles": 0,
        "ineffective_scroll_target": False,
    }

    metrics["instahyre_wait_reason"] = _wait_for_feed_cards_stable(
        page, settings.list_wait_ms
    )
    page.wait_for_timeout(settings.initial_settle_ms)
    _debug_dom_snapshot(page, "post-wait", feed_id=settings.feed_id)

    merged: dict[str, OpportunityCard] = {}
    harvest_stats = {
        "employer_blocks_visible": 0,
        "angular_opportunities_count": 0,
        "aligned_cards": 0,
        "alignment_mismatches": 0,
    }

    aligned, stats = _harvest_aligned_cards(page)
    for k, v in stats.items():
        harvest_stats[k] = max(harvest_stats.get(k, 0), v)
    for card in aligned:
        merged[card.job_id] = card

    metrics["cards_after_each_scroll"].append(len(merged))
    metrics["scroll_cycle_details"].append(
        {
            "cycle": 0,
            "phase": "initial_harvest",
            "merged_cards": len(merged),
            "growth": "initial",
            "employer_blocks_visible": stats.get("employer_blocks_visible", 0),
            "angular_opportunities_count": stats.get("angular_opportunities_count", 0),
            "aligned_cards": stats.get("aligned_cards", 0),
            "alignment_mismatches": stats.get("alignment_mismatches", 0),
        }
    )

    initial_probe = _probe_deep_scroll_target(page)
    metrics["scroll_container_selected"] = str(initial_probe.get("descriptor", "pending"))
    metrics["ineffective_scroll_target"] = bool(
        initial_probe.get("ineffective_scroll_target")
    )

    stable_rounds = 0
    last_total = len(merged)
    last_signal = _feed_signal_count(page)
    ineffective_scroll_cycles = 0
    stabilization_reason = f"max_scroll_cycles_{settings.scroll_max_cycles}"

    for cycle in range(settings.scroll_max_cycles):
        metrics["scroll_cycles"] = cycle + 1
        cycle_index = cycle + 1
        step = _deep_scroll_step_size(page)

        cycle_summary, strategy_attempts = _run_deep_scroll_strategy_chain(
            page,
            step=step,
            post_scroll_wait_ms=settings.post_scroll_wait_ms,
            merged=merged,
        )
        metrics["strategy_fallback_chains"].append(
            {
                "cycle": cycle_index,
                "attempts": strategy_attempts,
            }
        )

        last_signal = max(
            last_signal, int(cycle_summary.get("feed_signal_after", last_signal))
        )
        if cycle_summary.get("ineffective_scroll_target"):
            metrics["ineffective_scroll_target"] = True

        for attempt in strategy_attempts:
            harvest_stats["employer_blocks_visible"] = max(
                harvest_stats["employer_blocks_visible"],
                int(attempt.get("employer_blocks_visible", 0)),
            )
            harvest_stats["angular_opportunities_count"] = max(
                harvest_stats["angular_opportunities_count"],
                int(attempt.get("angular_opportunities_count", 0)),
            )
            harvest_stats["aligned_cards"] = max(
                harvest_stats["aligned_cards"],
                int(attempt.get("aligned_cards", 0)),
            )
            harvest_stats["alignment_mismatches"] = max(
                harvest_stats["alignment_mismatches"],
                int(attempt.get("alignment_mismatches", 0)),
            )

        merged_growth = len(merged) - last_total
        signal_grew = int(cycle_summary.get("feed_signal_after", 0)) > int(
            cycle_summary.get("feed_signal_before", 0)
        )
        scroll_moved = bool(cycle_summary.get("scroll_moved"))
        cycle_ineffective = (
            not scroll_moved
            and merged_growth <= 0
            and not signal_grew
        )
        if cycle_ineffective:
            ineffective_scroll_cycles += 1

        if merged_growth > 0:
            growth_label = "merged_growth"
            stable_rounds = 0
        elif signal_grew:
            growth_label = "signal_growth_only"
            stable_rounds = 0
        else:
            growth_label = "no_growth"
            stable_rounds += 1

        metrics["cards_after_each_scroll"].append(len(merged))
        last_attempt = strategy_attempts[-1] if strategy_attempts else {}
        metrics["scroll_cycle_details"].append(
            {
                "cycle": cycle_index,
                "phase": "scroll",
                "merged_cards": len(merged),
                "merged_delta": merged_growth,
                "growth": growth_label,
                "feed_signal_before": cycle_summary.get("feed_signal_before"),
                "feed_signal_after": cycle_summary.get("feed_signal_after"),
                "scroll_moved": scroll_moved,
                "scroll_strategy_used": cycle_summary.get("scroll_strategy_used"),
                "scroll_container_selected": last_attempt.get(
                    "scroll_container_selected",
                    metrics.get("scroll_container_selected"),
                ),
                "scrollTop_before": last_attempt.get("scrollTopBefore"),
                "scrollTop_after": last_attempt.get("scrollTopAfter"),
                "scrollHeight": last_attempt.get("scrollHeight"),
                "clientHeight": last_attempt.get("clientHeight"),
                "ineffective_scroll_target": cycle_summary.get(
                    "ineffective_scroll_target"
                ),
                "fallback_reason": cycle_summary.get("fallback_reason"),
                "strategy_attempts": cycle_summary.get("strategy_attempts"),
                "strategy_chain_exhausted": cycle_summary.get(
                    "strategy_chain_exhausted"
                ),
                "employer_blocks_visible": last_attempt.get("employer_blocks_visible", 0),
                "angular_opportunities_count": last_attempt.get(
                    "angular_opportunities_count", 0
                ),
                "aligned_cards": last_attempt.get("aligned_cards", 0),
                "alignment_mismatches": last_attempt.get("alignment_mismatches", 0),
            }
        )

        last_total = len(merged)

        if (
            cycle_index >= settings.min_scroll_cycles_before_stable
            and stable_rounds >= settings.stable_rounds
        ):
            stabilization_reason = (
                f"stable_no_growth_{settings.stable_rounds}_rounds"
            )
            break

    metrics["ineffective_scroll_cycles"] = ineffective_scroll_cycles
    metrics.update(harvest_stats)
    metrics["cards_after_stabilization"] = len(merged)
    metrics["stabilization_reason"] = stabilization_reason
    metrics["stable_no_growth_rounds_at_exit"] = stable_rounds
    metrics["final_feed_signal_count"] = last_signal
    return list(merged.values()), metrics


def _collect_feed_opportunity_cards(
    page: Page, *, feed_id: str
) -> tuple[list[OpportunityCard], dict[str, Any]]:
    settings = discovery_settings_for_feed(feed_id)
    if settings.traversal_mode == "pagination":
        return _collect_feed_opportunity_cards_paginated(page, settings)
    if settings.feed_id == _FEED_ID_MATCHING_PERSONALIZED and settings.deep_discovery:
        return _collect_feed_opportunity_cards_deep(page, settings)
    return _collect_feed_opportunity_cards_legacy(page, settings)


def _detail_body_text(page: Page) -> str:
    try:
        return (page.locator("body").inner_text() or "").lower()
    except Exception:
        return ""


def _detail_applied_signals_present(
    *,
    has_apply_applied_class: bool = False,
    body_text: str = "",
    tooltip_texts: tuple[str, ...] = (),
) -> bool:
    """True when any verified Instahyre detail-page applied signal is present."""
    if has_apply_applied_class:
        return True
    if "application sent!" in (body_text or "").lower():
        return True
    for tip in tooltip_texts:
        if "already applied" in (tip or "").lower():
            return True
    return False


def _parse_applied_signals_from_html(html: str) -> bool:
    """Parse verified applied signals from HTML for unit tests (no Playwright)."""
    has_class = bool(
        re.search(
            r'class="[^"]*\bapply\b[^"]*\bapplied\b[^"]*"',
            html,
            flags=re.IGNORECASE,
        )
    )
    tooltip_texts: list[str] = []
    for attr in ("tooltip-text", "data-original-title"):
        tooltip_texts.extend(
            re.findall(
                rf'{attr}="([^"]*)"',
                html,
                flags=re.IGNORECASE,
            )
        )
    body_text = re.sub(r"<[^>]+>", " ", html)
    return _detail_applied_signals_present(
        has_apply_applied_class=has_class,
        body_text=body_text,
        tooltip_texts=tuple(tooltip_texts),
    )


def _detect_applied_on_detail_page(page: Page) -> bool:
    """Detect Instahyre applied state from the open job detail page."""
    has_apply_applied_class = False
    try:
        has_apply_applied_class = page.locator("div.apply.applied").count() > 0
    except Exception:
        pass

    body_text = ""
    try:
        body_text = page.locator("body").inner_text() or ""
    except Exception:
        pass

    tooltip_texts: list[str] = []
    for attr in ("tooltip-text", "data-original-title"):
        try:
            for element in page.locator(f"[{attr}]").all():
                value = element.get_attribute(attr) or ""
                if value:
                    tooltip_texts.append(value)
        except Exception:
            continue

    return _detail_applied_signals_present(
        has_apply_applied_class=has_apply_applied_class,
        body_text=body_text,
        tooltip_texts=tuple(tooltip_texts),
    )


def _validate_detail_page(page: Page, card: OpportunityCard) -> str | None:
    """Return rejection reason or None if valid."""
    url = page.url or ""
    jid = extract_instahyre_job_id(url)
    if not jid:
        return "url_not_job_id"
    if jid != card.job_id:
        return "url_job_id_mismatch"

    if not _STABLE_JOB_PATH_RE.search(url):
        return "url_not_stable_job_path"

    body_low = _detail_body_text(page)
    for phrase in _DETAIL_REJECT_PHRASES:
        if phrase in body_low:
            return f"detail_contains_{phrase.replace(' ', '_')}"

    return None


def _extract_detail_title(page: Page) -> str:
    try:
        h1 = page.locator("h1").first
        if h1.count() == 0:
            return ""
        title = (h1.inner_text() or "").strip()
        if not title:
            return ""
        low = title.lower()
        if any(p in low for p in _DETAIL_REJECT_PHRASES):
            return ""
        return title
    except Exception:
        return ""


def _extract_detail_company(page: Page) -> str:
    selectors = (
        "[class*='company-name']",
        "[class*='CompanyName']",
        "[class*='employer']",
        "a[href*='/company/']",
        "h2",
    )
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if loc.count() == 0:
                continue
            txt = (loc.inner_text() or "").strip()
            if not txt or len(txt) > 120:
                continue
            low = txt.lower()
            if any(p in low for p in _DETAIL_REJECT_PHRASES):
                continue
            return txt
        except Exception:
            continue

    company, _title = _parse_company_title_from_card(_detail_body_text(page)[:1200])
    return company.strip()


def _extract_description(page: Page) -> str:
    selectors = (
        "motion.div.job-description",
        "motion.div[class*='job-description']",
        "motion.div[class*='JobDescription']",
        "motion.div.job-description",
        "div.job-description",
        "motion.div[class*='job-description']",
        "div[class*='job-description']",
        "section.job-description",
    )
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if loc.count() == 0:
                continue
            text = (loc.inner_text() or "").strip()
            if len(text) > 80:
                low = text.lower()
                if not any(p in low for p in _DETAIL_REJECT_PHRASES):
                    return text
        except Exception:
            continue
    return ""


def _parse_posted_iso_date(raw: str) -> date | None:
    s = (raw or "").strip()
    if not s:
        return None
    if "T" in s:
        s = s.split("T", 1)[0]
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _extract_job_posting_posted_date(page: Page) -> dict[str, Any]:
    """
    Tier-2 metadata: JobPosting datePosted from JSON-LD on the open detail page.
    Returns null fields when missing; never raises.
    """
    empty: dict[str, Any] = {
        "posted_at_raw": None,
        "posted_at_source": None,
        "posted_at_date": None,
        "age_days": None,
    }
    try:
        payload = page.evaluate(_JOB_POSTING_LD_JS)
    except Exception:
        return empty

    if not isinstance(payload, dict):
        return empty

    raw = str(payload.get("datePosted") or "").strip()
    if not raw:
        return empty

    posted_date = _parse_posted_iso_date(raw)
    if not posted_date:
        return empty

    scrape_day = datetime.now(timezone.utc).date()
    age_days = max(0, (scrape_day - posted_date).days)

    return {
        "posted_at_raw": raw,
        "posted_at_source": _POSTED_AT_SOURCE,
        "posted_at_date": posted_date.isoformat(),
        "age_days": age_days,
    }


def _extract_job_posted_by(page: Page) -> dict[str, str]:
    """Extract Instahyre 'Job posted by' sidebar fields."""
    out = {
        "recruiter_name": "",
        "recruiter_title": "",
        "recruiter_company": "",
        "recruiter_profile": "",
    }
    try:
        if page.locator(".new-posted-by .rec-name").count() > 0:
            out["recruiter_name"] = (
                page.locator(".new-posted-by .rec-name").first.inner_text() or ""
            ).strip()

        if page.locator(".new-posted-by .designation").count() > 0:
            out["recruiter_title"] = (
                page.locator(".new-posted-by .designation").first.inner_text() or ""
            ).strip()

        at_locator = page.locator(".new-posted-by .rec-info span").filter(
            has_text=re.compile(r"^\s*at\s+", re.IGNORECASE)
        )
        if at_locator.count() > 0:
            at_text = (at_locator.first.inner_text() or "").strip()
            out["recruiter_company"] = re.sub(
                r"^\s*at\s+",
                "",
                at_text,
                flags=re.IGNORECASE,
            ).strip()

        if not out["recruiter_name"]:
            side = page.locator(".side-section-row-right").first
            if side.count() > 0:
                lines = [
                    ln.strip()
                    for ln in (side.inner_text() or "").split("\n")
                    if ln.strip()
                ]
                if lines and lines[0].lower() == "job posted by":
                    lines = lines[1:]
                if lines:
                    out["recruiter_name"] = lines[0]
                if len(lines) > 1:
                    out["recruiter_title"] = lines[1]
                if len(lines) > 2:
                    out["recruiter_company"] = re.sub(
                        r"^\s*at\s+",
                        "",
                        lines[2],
                        flags=re.IGNORECASE,
                    ).strip()

        for sel in ("a[href*='/recruiter']", "a[href*='/hiring']"):
            link = page.locator(f".new-posted-by {sel}").first
            if link.count() == 0:
                continue
            href = link.get_attribute("href") or ""
            if href:
                out["recruiter_profile"] = urljoin(_ORIGIN + "/", href)
                break
    except Exception:
        pass
    return out


def _open_card_detail(page: Page, card: OpportunityCard) -> bool:
    """Navigate using Angular opportunity_url only."""
    try:
        page.goto(card.canonical_url, timeout=45000, wait_until="domcontentloaded")
        page.wait_for_timeout(2000)
        return True
    except Exception as e:
        log_fail(
            f"❌ Failed to open detail page: {card.title} — {card.company} "
            f"(job-{card.job_id}) ({e})"
        )
        return False


def _build_job_from_card(page: Page, card: OpportunityCard) -> dict | None:
    reject = _validate_detail_page(page, card)
    if reject:
        log_debug_rejection(reject, job_id=card.job_id, url=page.url)
        return None

    title = _extract_detail_title(page)
    if not title:
        log_debug_rejection("detail_title_missing", job_id=card.job_id)
        return None

    company = _extract_detail_company(page)
    if not company:
        log_debug_rejection("detail_company_missing", job_id=card.job_id)
        return None

    jid = extract_instahyre_job_id(page.url)
    if not jid:
        log_debug_rejection("detail_url_no_job_id", job_id=card.job_id, url=page.url)
        return None

    link = card.canonical_url
    description = _extract_description(page)
    posted_by = _extract_job_posted_by(page)
    posted_meta = _extract_job_posting_posted_date(page)
    if posted_meta.get("posted_at_date") is not None and posted_meta.get("age_days") is not None:
        log_debug(
            f"✅ Posted Date: {posted_meta['posted_at_date']} "
            f"({posted_meta['age_days']} days old)"
        )
    recruiter_name = posted_by.get("recruiter_name") or "Not Specified"
    hiring_manager = recruiter_name
    applied = _detect_applied_on_detail_page(page)

    return {
        "title": title,
        "company": company,
        "location": card.location,
        "link": link,
        "description": description,
        "source": "instahyre",
        "time_posted": "Unknown",
        "posted_at_raw": posted_meta.get("posted_at_raw"),
        "posted_at_source": posted_meta.get("posted_at_source"),
        "posted_at_date": posted_meta.get("posted_at_date"),
        "age_days": posted_meta.get("age_days"),
        "hiring_manager": hiring_manager,
        "recruiter_name": posted_by.get("recruiter_name", ""),
        "recruiter_title": posted_by.get("recruiter_title", ""),
        "recruiter_company": posted_by.get("recruiter_company", ""),
        "recruiter_profile": posted_by.get("recruiter_profile", ""),
        "applied": applied,
        "score": 0,
        "instahyre_job_id": jid,
        "instahyre_opportunity_url": card.opportunity_url_path,
    }


def _valid_recruiter_name(name: str) -> bool:
    cleaned = (name or "").strip()
    if not cleaned:
        return False
    return cleaned.lower() not in ("not specified", "unknown", "nan")


def _format_job_acquired_log(card: OpportunityCard, job: dict) -> str:
    line = f"✅ Opened: {card.title} — {card.company}"
    recruiter_name = str(job.get("recruiter_name") or "").strip()
    if not _valid_recruiter_name(recruiter_name):
        return line
    recruiter_title = str(job.get("recruiter_title") or "").strip()
    if recruiter_title:
        return f"{line} || ✅ Recruiter: {recruiter_name} | {recruiter_title}"
    return f"{line} || ✅ Recruiter: {recruiter_name}"


def scrape_instahyre_feed(
    feed_url: str, feed_run: dict | None = None
) -> tuple[list[dict], dict[str, Any]]:
    """
    Scrape one Instahyre opportunities feed URL.
    Only jobs passing scraper-side QA are returned.
    """
    feed_run = feed_run or {}
    feed_id = feed_run.get("feed_id") or "feed"
    label = feed_run.get("label") or feed_id

    allowed_urls = {_FEED_MATCHING_URL, _FEED_PM_SEARCH_URL, _FEED_PM_CURATED_URL}
    if feed_url not in allowed_urls:
        log_warn("⚠️ Instahyre feed URL not in allowlist; proceeding with configured URL")

    jobs: list[dict] = []
    feed_stats: dict[str, Any] = {
        "opportunity_cards_found": 0,
        "unique_jobs_collected": 0,
        "jobs_failed_open": 0,
        "recruiters_added": 0,
        "recruiters_updated": 0,
        "duration_sec": 0.0,
    }
    metrics: dict[str, Any] = {}
    feed_recruiters: set[str] = set()
    t0 = time.monotonic()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=400)
        context = _new_authenticated_context(browser)
        page = context.new_page()

        log_debug(f"[debug] feed_id={feed_id} url={feed_url}")

        page.goto(feed_url, timeout=60000, wait_until="domcontentloaded")
        _assert_candidate_session(page)

        discovery = discovery_settings_for_feed(feed_id)
        if discovery.traversal_mode == "pagination":
            log_debug(
                f"[debug] feed_id={feed_id} pagination discovery: "
                f"max_pages={discovery.max_pages} "
                f"page_min_new_ratio={discovery.page_min_new_ratio} "
                f"page_transition_wait_ms={discovery.page_transition_wait_ms} "
                f"page_settle_ms={discovery.page_settle_ms} "
                f"list_wait_ms={discovery.list_wait_ms}"
            )
        elif discovery.deep_discovery:
            log_debug(
                f"[debug] feed_id={feed_id} scroll fallback discovery: "
                f"scroll_max={discovery.scroll_max_cycles} "
                f"stable_rounds={discovery.stable_rounds} "
                f"list_wait_ms={discovery.list_wait_ms} "
                f"post_scroll_wait_ms={discovery.post_scroll_wait_ms}"
            )

        cards, harvest_metrics = _collect_feed_opportunity_cards(page, feed_id=feed_id)
        metrics.update(harvest_metrics)
        feed_stats["opportunity_cards_found"] = len(cards)
        log_ok(f"✅ Opportunity cards found: {len(cards)}")
        _debug_dom_snapshot(page, "post-harvest", feed_id=feed_id)

        cap_limit = _max_jobs_per_feed()
        discovered_unique_cards = len(cards)
        detail_attempted_cards = 0
        detail_skipped_due_to_cap = 0
        seen_ids: set[str] = set()
        for card in cards:
            if len(jobs) >= cap_limit:
                detail_skipped_due_to_cap += 1
                continue
            if card.job_id in seen_ids:
                log_warn(f"⚠️ Duplicate skipped: {card.job_id}")
                continue
            seen_ids.add(card.job_id)

            detail_attempted_cards += 1
            if not _open_card_detail(page, card):
                feed_stats["jobs_failed_open"] = int(feed_stats["jobs_failed_open"]) + 1
                continue

            job = _build_job_from_card(page, card)
            if not job:
                feed_stats["jobs_failed_open"] = int(feed_stats["jobs_failed_open"]) + 1
                continue

            log_ok(_format_job_acquired_log(card, job))

            recruiter_name = str(job.get("recruiter_name") or "").strip()
            if _valid_recruiter_name(recruiter_name):
                recruiter_key = recruiter_name.lower()
                if recruiter_key in feed_recruiters:
                    feed_stats["recruiters_updated"] = (
                        int(feed_stats["recruiters_updated"]) + 1
                    )
                else:
                    feed_recruiters.add(recruiter_key)
                    feed_stats["recruiters_added"] = int(feed_stats["recruiters_added"]) + 1

            jobs.append(job)

        metrics["discovered_unique_cards"] = discovered_unique_cards
        metrics["detail_attempted_cards"] = detail_attempted_cards
        metrics["detail_skipped_due_to_cap"] = detail_skipped_due_to_cap
        metrics["max_jobs_per_feed_limit"] = cap_limit
        metrics["final_unique_instahyre_jobs"] = len(jobs)
        log_feed_debug_metrics(metrics)

        context.close()
        browser.close()

    feed_stats["unique_jobs_collected"] = len(jobs)
    feed_stats["duration_sec"] = round(time.monotonic() - t0, 1)
    log_ok(f"✅ Unique jobs collected: {len(jobs)}")
    log_debug(f"[debug] feed duration_sec={feed_stats['duration_sec']}")
    return jobs, feed_stats


def _ensure_interested_filter_selected(page: Page) -> None:
    """Fallback: click Interested sidebar if URL param did not select the filter."""
    probe = page.evaluate(
        """
        () => {
          const radios = Array.from(document.querySelectorAll('input[type="radio"]'));
          const interested = radios.find((r) => {
            const label = r.id
              ? document.querySelector(`label[for="${r.id}"]`)
              : r.closest('label');
            return label && /^interested$/i.test((label.innerText || '').trim());
          });
          if (interested && !interested.checked) {
            const label = interested.id
              ? document.querySelector(`label[for="${interested.id}"]`)
              : interested.closest('label');
            if (label) {
              label.click();
              return { clicked: true };
            }
          }
          return {
            clicked: false,
            status_param: new URLSearchParams(location.search).get('status'),
          };
        }
        """
    )
    if isinstance(probe, dict) and probe.get("clicked"):
        page.wait_for_timeout(2000)
        log_debug("[debug] interested_sync: selected Interested via sidebar click")


def _build_interested_sync_stub(card: OpportunityCard) -> dict | None:
    """Minimal list-only job dict for Phase B Interested synchronization."""
    job_id = str(card.job_id or "").strip()
    if not job_id:
        return None
    run_ts = datetime.now(timezone.utc).isoformat()
    stub: dict[str, Any] = {
        "title": card.title,
        "company": card.company,
        "location": card.location,
        "link": card.canonical_url,
        "source": "instahyre",
        "applied": True,
        "instahyre_job_id": job_id,
        "instahyre_opportunity_url": card.opportunity_url_path,
        "instahyre_feed_id": _FEED_ID_INTERESTED_SYNC,
        "instahyre_query_id": _FEED_ID_INTERESTED_SYNC,
        "instahyre_query_label": "Instahyre Interested Sync",
        "instahyre_query_role": "state_sync",
        "instahyre_run_ts": run_ts,
        "currently_active": True,
    }
    v2, identity_source = generate_job_key_v2(stub)
    if not v2:
        return None
    stub["JOB_KEY_V2"] = v2
    stub["identity_source"] = identity_source or "instahyre_id"
    return stub


def sync_instahyre_interested() -> tuple[list[dict], dict[str, Any]]:
    """
    Phase B: Interested list synchronization (Instahyre only).

    Business rule: membership in the Interested filter = Applied.
    List-only harvest — no detail pages, no AI, no Stage-1.
    """
    stubs: list[dict] = []
    stats: dict[str, Any] = {
        "phase": "interested_sync",
        "cards_harvested": 0,
        "stubs_built": 0,
        "skipped_no_job_id": 0,
        "duplicates_skipped": 0,
        "duration_sec": 0.0,
    }
    t0 = time.monotonic()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=400)
        context = _new_authenticated_context(browser)
        page = context.new_page()

        log_ok("\n🟣 INSTAHYRE INTERESTED SYNC STARTED")
        log_debug(f"[debug] interested_sync url={_INTERESTED_SYNC_URL}")

        page.goto(_INTERESTED_SYNC_URL, timeout=60000, wait_until="domcontentloaded")
        _assert_candidate_session(page)
        _ensure_interested_filter_selected(page)

        cards, harvest_metrics = _collect_feed_opportunity_cards(
            page, feed_id=_FEED_ID_INTERESTED_SYNC
        )
        stats.update(harvest_metrics)
        stats["cards_harvested"] = len(cards)
        log_ok(f"✅ Interested opportunity cards found: {len(cards)}")

        seen_ids: set[str] = set()
        for card in cards:
            if not str(card.job_id or "").strip():
                stats["skipped_no_job_id"] = int(stats["skipped_no_job_id"]) + 1
                log_warn(
                    f"⚠️ Interested sync skip: missing job_id "
                    f"({card.title} — {card.company})"
                )
                continue
            if card.job_id in seen_ids:
                stats["duplicates_skipped"] = int(stats["duplicates_skipped"]) + 1
                continue
            seen_ids.add(card.job_id)

            stub = _build_interested_sync_stub(card)
            if not stub:
                stats["skipped_no_job_id"] = int(stats["skipped_no_job_id"]) + 1
                continue
            stubs.append(stub)

        stats["stubs_built"] = len(stubs)
        stats["duration_sec"] = round(time.monotonic() - t0, 1)
        log_ok(f"✅ Interested sync stubs built: {len(stubs)}")
        log_debug(f"[debug] interested_sync duration_sec={stats['duration_sec']}")

        context.close()
        browser.close()

    return stubs, stats


def scrape_instahyre_jobs(
    search_url: str, query_run: dict | None = None
) -> tuple[list[dict], dict[str, Any]]:
    """Backward-compatible alias for feed scraper."""
    feed_run = query_run or {}
    if "feed_id" not in feed_run and feed_run.get("query_id"):
        feed_run = {
            "feed_id": feed_run.get("query_id"),
            "label": feed_run.get("label"),
        }
    return scrape_instahyre_feed(search_url, feed_run=feed_run)
