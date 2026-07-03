from playwright.sync_api import sync_playwright
import os
import random
import re
import time
import traceback
from urllib.parse import parse_qs, urlencode, urlparse

import paths
from agent.job_identity import generate_job_key_v2

# from agent.filter_engine import apply_stage1_filter

_CARD_SELECTOR = "li.scaffold-layout__list-item"
_LI_PRIMARY_POSTED_SELECTOR = (
    "div.job-details-jobs-unified-top-card__primary-description-container"
)
_LI_RELATIVE_POSTED_RE = re.compile(
    r"(\d+\s+(hour|day|week|month)s?\s+ago)", re.I
)
_QUALIFICATION_CARD_TITLE_RE = re.compile(
    r"(Product Manager|Product Owner|Associate Product Manager|Senior Product Manager)",
    re.I,
)
_DEFAULT_QUALIFICATION_ENTRY_URL = "https://www.linkedin.com/jobs/"
_QUALIFICATION_UI_TEXT_PATTERNS = (
    re.compile(r"top\s+applicant", re.I),
    re.compile(r"how\s+you\s+fit", re.I),
)


class QualificationNavigationError(RuntimeError):
    """Raised when the scraper cannot reach the How You Fit / Top Applicant feed."""


def _li_build_qualification_url_no_job_id(
    keywords: str,
    geo_id: str = "",
) -> str:
    """Build qualification landing URL without embedded job IDs."""
    params = {
        "showHowYouFit": "HOW_YOU_FIT",
        "origin": "QUALIFICATION_LANDING",
        "keywords": (keywords or "Product Manager").strip(),
    }
    gid = str(geo_id or "").strip()
    if gid:
        params["geoId"] = gid
    return "https://www.linkedin.com/jobs/search-results/?" + urlencode(params)


def _li_qualification_page_ready(page) -> bool:
    """True when How You Fit qualification cards are visible."""
    try:
        loc = page.locator('div[role="button"]').filter(
            has_text=_QUALIFICATION_CARD_TITLE_RE
        )
        if loc.count() == 0:
            return False
        return loc.first.is_visible()
    except Exception:
        return False


def _li_try_click_qualification_entry(page) -> bool:
    """Click Top Applicant / How you fit UI entry when visible."""
    for pattern in _QUALIFICATION_UI_TEXT_PATTERNS:
        try:
            loc = page.locator(
                "a, button, [role='button'], [role='link']"
            ).filter(has_text=pattern)
            if loc.count() == 0:
                continue
            target = loc.first
            if not target.is_visible():
                continue
            target.click(timeout=5000)
            _li_human_pause(page, 2200, 4200)
            _li_diag_log(
                f"qualification_ui_click pattern={pattern.pattern!r} "
                f"url={page.url[:200]}"
            )
            return True
        except Exception as e:
            _li_diag_log(
                f"qualification_ui_click_failed pattern={pattern.pattern!r} err={e!r}"
            )
    return False


def _li_log_qualification_nav_reached(page, *, via: str) -> None:
    _li_diag_log(
        "qualification_landing_reached "
        f"via={via!r} cards={_li_count_job_cards(page)} url={page.url[:200]}"
    )


def _li_navigate_to_qualification_landing(
    page,
    *,
    entry_url: str | None = None,
    keywords: str = "",
    geo_id: str = "",
) -> None:
    """Navigate from a stable entry point to the How You Fit / Top Applicant feed."""
    entry = (entry_url or _DEFAULT_QUALIFICATION_ENTRY_URL).strip()
    _li_diag_log(f"qualification_nav_start entry_url={entry!r}")

    page.goto(entry)
    _li_human_pause(page, 4000, 6500)
    if _li_qualification_page_ready(page):
        _li_log_qualification_nav_reached(page, via="entry")
        return

    qual_url = _li_build_qualification_url_no_job_id(keywords, geo_id)
    _li_diag_log(f"qualification_nav_fast_path url={qual_url[:240]}")
    page.goto(qual_url)
    _li_human_pause(page, 7000, 11000)
    if _li_qualification_page_ready(page):
        _li_log_qualification_nav_reached(page, via="fast_path")
        return

    try:
        page.click("button[aria-label='Jobs']", timeout=5000)
        _li_human_pause(page, 2200, 4000)
        _li_diag_log("qualification_nav_jobs_tab_clicked", verbose=True)
    except Exception as e:
        _li_diag_log(f"qualification_nav_jobs_tab_skipped: {e!r}")

    if not _li_qualification_page_ready(page):
        _li_try_click_qualification_entry(page)

    try:
        _li_job_card_locator(page).first.wait_for(state="visible", timeout=20000)
    except Exception as e:
        if not _li_qualification_page_ready(page):
            raise QualificationNavigationError(
                "Could not reach Top Applicant / How You Fit feed"
            ) from e

    _li_log_qualification_nav_reached(page, via="ui_navigation")


def _li_is_qualification_landing_url(url: str) -> bool:
    """True when URL is LinkedIn How You Fit / qualification landing (not classic /jobs/search/)."""
    u = (url or "").lower()
    if "showhowyoufit" in u or "qualification_landing" in u:
        return True
    if "/jobs/search-results" in u:
        return True
    return False


def _li_url_current_job_id(url: str) -> str | None:
    try:
        vals = parse_qs(urlparse(url).query).get("currentJobId") or []
        return vals[0] if vals else None
    except Exception:
        return None


def _li_job_card_locator(page):
    if _li_is_qualification_landing_url(page.url):
        return page.locator('div[role="button"]').filter(
            has_text=_QUALIFICATION_CARD_TITLE_RE
        )
    return page.locator(_CARD_SELECTOR)


def _li_parse_relative_posted_text(text: str) -> str | None:
    if not text:
        return None
    match = _LI_RELATIVE_POSTED_RE.search(text.lower())
    return match.group(1) if match else None


def _li_extract_time_posted_flagship3_fallback(page) -> str | None:
    """Flagship3 job-details fallback when primary BEM selector misses."""
    for paragraph in page.query_selector_all("main p"):
        try:
            text = (paragraph.inner_text() or "").lower()
        except Exception:
            continue
        if "·" not in text:
            continue
        parsed = _li_parse_relative_posted_text(text)
        if not parsed:
            continue
        if "applicant" in text:
            return parsed
        if _LI_RELATIVE_POSTED_RE.search(text):
            return parsed

    strong_matches: list[tuple[str, object]] = []
    for strong in page.query_selector_all("main strong"):
        try:
            strong_text = strong.inner_text() or ""
        except Exception:
            continue
        parsed = _li_parse_relative_posted_text(strong_text)
        if parsed:
            strong_matches.append((parsed, strong))

    if len(strong_matches) == 1:
        return strong_matches[0][0]

    for parsed, strong in strong_matches:
        try:
            parent_text = (
                strong.evaluate(
                    "el => { const p = el.closest('p'); return p ? p.innerText : ''; }"
                )
                or ""
            ).lower()
        except Exception:
            continue
        if "applicant" in parent_text:
            return parsed
        if "·" in parent_text and _LI_RELATIVE_POSTED_RE.search(parent_text):
            return parsed

    return None


def _li_extract_time_posted_from_page(page) -> str:
    """Primary BEM selector, then flagship3 fallback. Returns relative text or 'Unknown'."""
    time_posted = "Unknown"

    try:
        page.wait_for_selector(_LI_PRIMARY_POSTED_SELECTOR, timeout=3000)
        container = page.query_selector(_LI_PRIMARY_POSTED_SELECTOR)
        if container:
            parsed = _li_parse_relative_posted_text(container.inner_text())
            if parsed:
                time_posted = parsed
    except Exception:
        pass

    if time_posted == "Unknown":
        try:
            fallback_posted = _li_extract_time_posted_flagship3_fallback(page)
            if fallback_posted:
                time_posted = fallback_posted
        except Exception:
            pass

    return time_posted


_LI_PRIMARY_HM_SELECTOR = "span.jobs-poster__name strong"
_LI_NOT_SPECIFIED_HM = "Not Specified"
_INVALID_HM = frozenset({"", "not specified", "unknown", "nan", "none"})
_LI_POSTER_SECTION_MARKERS = (
    "meet the hiring team",
    "job poster",
    "posted by",
)
_LI_HM_NOISE_RE = re.compile(
    r"(recruiter at|hiring manager at|engineer at|•|\||\bat\b|1st|2nd|3rd|"
    r"connection|followers|i am hiring|people you can reach)",
    re.I,
)


def _li_is_valid_hiring_manager(value: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    return text.lower() not in _INVALID_HM


def _li_normalize_hiring_manager(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    first_line = text.split("\n", 1)[0].strip()
    if not _li_is_valid_hiring_manager(first_line):
        return ""
    if _LI_HM_NOISE_RE.search(first_line):
        return ""
    if len(first_line) > 80:
        return ""
    return first_line


def _li_scroll_job_detail_for_hm(page) -> None:
    """Mirror acquisition scroll before HM extraction."""
    for _ in range(5):
        page.mouse.wheel(0, 1500)
        page.wait_for_timeout(1200)
    page.wait_for_timeout(2000)


def _li_extract_hiring_manager_flagship3_fallback(page) -> str | None:
    """Poster-section fallback when primary BEM selector misses."""
    try:
        for paragraph in page.query_selector_all("main p"):
            try:
                marker_text = (paragraph.inner_text() or "").strip().lower()
            except Exception:
                continue
            if not any(marker in marker_text for marker in _LI_POSTER_SECTION_MARKERS):
                continue
            candidate = paragraph.evaluate(
                """el => {
                    let node = el;
                    for (let depth = 0; depth < 10 && node; depth++) {
                        node = node.parentElement;
                        if (!node) break;
                        const links = node.querySelectorAll('a[href*="/in/"]');
                        let best = '';
                        for (const link of links) {
                            const raw = (link.innerText || '').trim();
                            if (!raw) continue;
                            const line = raw.split('\\n').map(s => s.trim()).filter(Boolean)[0] || '';
                            if (!line) continue;
                            if (!best || line.length < best.length) best = line;
                        }
                        if (best) return best;
                    }
                    return '';
                }"""
            )
            normalized = _li_normalize_hiring_manager(str(candidate or ""))
            if normalized:
                return normalized
    except Exception:
        pass
    return None


def _li_extract_hiring_manager_from_page(page) -> str:
    """Primary BEM selector, then flagship3 fallback. Returns name or 'Not Specified'."""
    _li_scroll_job_detail_for_hm(page)
    hiring_manager = ""

    try:
        hiring_manager_el = page.query_selector(_LI_PRIMARY_HM_SELECTOR)
        if hiring_manager_el:
            hiring_manager = _li_normalize_hiring_manager(
                hiring_manager_el.inner_text() or ""
            )
    except Exception:
        pass

    if not hiring_manager:
        try:
            fallback_hm = _li_extract_hiring_manager_flagship3_fallback(page)
            if fallback_hm:
                hiring_manager = fallback_hm
        except Exception:
            pass

    if hiring_manager:
        return hiring_manager
    return _LI_NOT_SPECIFIED_HM


def _li_parse_qualification_card_text(text: str) -> tuple[str, str, str, str]:
    """Return (title, company, location, time_posted) from a How You Fit list row."""
    lines = [ln.strip() for ln in (text or "").split("\n") if ln.strip()]
    title = "Unknown"
    company = "Unknown"
    location = "Unknown"
    time_posted = "Unknown"
    for ln in lines:
        if ln.startswith("Selected,"):
            ln = ln.split(",", 1)[-1].strip()
        ln = ln.replace("(Verified job)", "").strip()
        if _QUALIFICATION_CARD_TITLE_RE.search(ln) and len(ln) < 120:
            if title == "Unknown" or len(ln) < len(title):
                title = ln
    meta_skip = (
        "viewed",
        "easy apply",
        "actively reviewing",
        "posted",
        "·",
        "selected",
        "verified",
    )
    title_seen = False
    for ln in lines:
        low = ln.lower()
        if _QUALIFICATION_CARD_TITLE_RE.search(ln) and title in ln:
            title_seen = True
            continue
        if title_seen and company == "Unknown":
            if any(x in low for x in meta_skip):
                continue
            if "(on-site)" in low or "(remote)" in low or "hybrid" in low:
                location = ln
                continue
            if len(ln) < 80:
                company = ln
                continue
        if "posted" in low:
            m = re.search(r"posted\s+(.+)", low, re.I)
            if m:
                time_posted = m.group(1).strip()
        if "(on-site)" in low or "(remote)" in low or "hybrid" in low:
            location = ln
    return title, company, location, time_posted


def _li_title_company_from_page_title(page_title: str) -> tuple[str | None, str | None]:
    parts = [p.strip() for p in (page_title or "").split("|")]
    if len(parts) >= 3 and "linkedin" in parts[-1].lower():
        return parts[0], parts[1]
    return None, None


def debug_linkedin_enabled() -> bool:
    """Traversal/browser diagnostics: DEBUG_LINKEDIN=1 (LINKEDIN_VERBOSE_DIAG still honored)."""
    for key in ("DEBUG_LINKEDIN", "LINKEDIN_VERBOSE_DIAG"):
        v = os.environ.get(key, "").strip().lower()
        if v in ("1", "true", "yes", "on"):
            return True
    return False


def _li_diag_log(msg: str, *, verbose: bool = False) -> None:
    del verbose  # all diagnostics gated uniformly
    if not debug_linkedin_enabled():
        return
    print(f"[LinkedInDiag] {msg}")


def _li_count_job_cards(page) -> int:
    try:
        return _li_job_card_locator(page).count()
    except Exception as e:
        _li_diag_log(f"count_job_cards_error: {e!r}")
        return -1


def _li_url_jobs_start_param(url: str):
    """Parse LinkedIn jobs search `start` query param (pagination offset), or None."""
    try:
        qs = parse_qs(urlparse(url).query)
        vals = qs.get("start") or []
        return vals[0] if vals else None
    except Exception:
        return None


def _li_first_visible_job_card_signature(page) -> dict:
    """
    Identity of the first visible job card row (for post-pagination DOM refresh detection).
    """
    out = {"job_id": None, "title_text": None, "raw_card_text": None}
    try:
        first = _li_job_card_locator(page).first
        if first.count() == 0:
            return out
        if not first.is_visible():
            return out

        job_id = _li_url_current_job_id(page.url)
        link = first.locator("a[href*='/jobs/view/']").first
        if link.count() > 0:
            href = link.get_attribute("href") or ""
            if "/jobs/view/" in href:
                job_id = href.split("/jobs/view/")[1].split("/")[0].split("?")[0]

        title_text = None
        if _li_is_qualification_landing_url(page.url):
            try:
                title_text, _, _, _ = _li_parse_qualification_card_text(
                    first.inner_text() or ""
                )
            except Exception:
                title_text = None
        else:
            for tsel in (
                "a.job-card-list__title--link",
                "a[href*='/jobs/view/']",
            ):
                te = first.locator(tsel).first
                if te.count() > 0:
                    try:
                        title_text = (te.inner_text() or "").strip()
                    except Exception:
                        title_text = None
                    if title_text:
                        break

        raw_card_text = None
        try:
            raw_card_text = (first.inner_text() or "").strip()
        except Exception:
            raw_card_text = None

        out["job_id"] = job_id
        out["title_text"] = title_text
        out["raw_card_text"] = raw_card_text
    except Exception as e:
        out["signature_error"] = repr(e)
    return out


def _li_wait_post_expansion_hydration(
    page,
    *,
    pre_click_url: str,
    pre_click_start,
    pre_fingerprint: tuple,
    pre_count: int,
    timeout_ms: int = 28000,
) -> dict:
    """
    After expansion/pagination click: wait for URL `start=` and/or first-card identity
    to change, then wait until the first-card fingerprint stabilizes so counts are not
    read against the previous page's DOM.

    Why: LinkedIn updates the URL before list hydration finishes; `_li_count_job_cards`
    can stay at 25 while still pointing at stale rows, so `new_c > cur` never becomes true.
    """
    t_deadline = time.monotonic() + (timeout_ms / 1000.0)
    pre_j, _, _ = pre_fingerprint
    phase = "await_signal"
    last_fp = None

    while time.monotonic() < t_deadline:
        cur_url = page.url
        cur_start = _li_url_jobs_start_param(cur_url)
        sig = _li_first_visible_job_card_signature(page)
        cnt = _li_count_job_cards(page)
        fp = (
            sig.get("job_id"),
            (sig.get("title_text") or "")[:120],
            (sig.get("raw_card_text") or "")[:160],
        )

        start_changed = str(pre_click_start or "") != str(cur_start or "")
        job_id_changed = bool(
            pre_j and sig.get("job_id") and str(pre_j) != str(sig.get("job_id"))
        )

        if phase == "await_signal":
            if start_changed or job_id_changed:
                phase = "stabilize"
                last_fp = fp
                _li_diag_log(
                    "post_pagination_hydration_signal "
                    f"start_changed={start_changed} job_id_changed={job_id_changed} "
                    f"pre_start={pre_click_start!r} cur_start={cur_start!r} "
                    f"pre_job_id={pre_j!r} cur_job_id={sig.get('job_id')!r} "
                    f"pre_count={pre_count} cur_count={cnt}",
                    verbose=True,
                )
                _li_human_pause(page, 450, 900)
            else:
                _li_human_pause(page, 350, 700)
            continue

        # phase == "stabilize"
        if last_fp is not None and fp == last_fp:
            return {
                "card_dom_refresh_detected": True,
                "post_pagination_url": cur_url,
                "first_sig_after": sig,
                "card_count_after_refresh": cnt,
            }
        last_fp = fp
        _li_human_pause(page, 450, 900)

    sig = _li_first_visible_job_card_signature(page)
    cnt = _li_count_job_cards(page)
    return {
        "card_dom_refresh_detected": False,
        "post_pagination_url": page.url,
        "first_sig_after": sig,
        "card_count_after_refresh": cnt,
    }


def _li_scroll_probe(page) -> dict:
    """
    Inspect scrollable ancestors of the first job card (diagnostic only).
    """
    try:
        return page.evaluate(
            """() => {
                const items = document.querySelectorAll('li.scaffold-layout__list-item');
                const n = items.length;
                const containers = [];
                if (!n) return { cardCount: 0, containers: [] };
                let el = items[0].parentElement;
                while (el && el !== document.documentElement) {
                    const sh = el.scrollHeight;
                    const ch = el.clientHeight;
                    if (sh > ch + 5) {
                        containers.push({
                            tag: el.tagName,
                            className: String(el.className || '').slice(0, 160),
                            scrollHeight: sh,
                            clientHeight: ch,
                            scrollTop: el.scrollTop,
                        });
                    }
                    el = el.parentElement;
                }
                return { cardCount: n, containers };
            }"""
        )
    except Exception as e:
        return {"cardCount": -1, "containers": [], "probe_error": str(e)}


def _li_log_scroll_top_deltas(before: dict, after: dict, iteration: int) -> None:
    cb = before.get("containers") or []
    ca = after.get("containers") or []
    lim = min(len(cb), len(ca), 5)
    for i in range(lim):
        b, a = cb[i], ca[i]
        d = (a.get("scrollTop") or 0) - (b.get("scrollTop") or 0)
        _li_diag_log(
            f"scroll_iter={iteration} container[{i}] scrollTop_delta={d} "
            f"(before={b.get('scrollTop')} after={a.get('scrollTop')})",
            verbose=True,
        )


def _li_pagination_probe(page) -> dict:
    """Presence-only counts; does not click."""
    probes = {}
    patterns = [
        ("next_aria_contains", "button[aria-label*='Next']"),
        ("next_aria_label_next", 'button[aria-label="Next"]'),
        ("next_text", "button:has-text('Next')"),
        ("see_more_jobs", "button:has-text('See more jobs')"),
        ("show_more", "button:has-text('Show more')"),
        ("pagination_pages", "ul.artdeco-pagination__pages"),
    ]
    for name, sel in patterns:
        try:
            probes[name] = page.locator(sel).count()
        except Exception as e:
            probes[name] = f"err:{e!r}"
    return probes


def _li_human_pause(page, ms_low: int, ms_high: int) -> None:
    """Bounded randomized wait for human-like pacing (anti-bot risk reduction)."""
    t = random.randint(ms_low, ms_high)
    page.wait_for_timeout(t)


def _li_env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)).strip())
    except (TypeError, ValueError):
        return default


_LINKEDIN_MAX_NEXT_PAGES = _li_env_int("LINKEDIN_MAX_NEXT_PAGES", 5)
_LINKEDIN_MAX_SHOW_MORE_CLICKS = _li_env_int("LINKEDIN_MAX_SHOW_MORE_CLICKS", 3)
_LINKEDIN_SHOW_MORE_NO_GROWTH_STOP = _li_env_int("LINKEDIN_SHOW_MORE_NO_GROWTH_STOP", 2)
_LINKEDIN_RESET_ABORT_THRESHOLD = _li_env_int("LINKEDIN_RESET_ABORT_THRESHOLD", 2)


class _LinkedInTraversalMetrics:
    """Consolidated counters for mature LinkedIn list traversal (observability only)."""

    def __init__(self) -> None:
        self.pages_visited = 0
        self.show_more_clicks = 0
        self.show_more_growth_hits = 0
        self.show_more_no_growth = 0
        self.scroll_cycles = 0
        self.feed_growth_events = 0
        self.feed_reset_events = 0
        self.reset_recovery_attempts = 0
        self.reset_aborts = 0
        self.next_page_successes = 0
        self.next_page_failures = 0
        self.duplicate_cards_skipped = 0
        self.jobs_accumulated = 0
        self.unique_v2_jobs = 0

    def print_summary(self) -> None:
        if not debug_linkedin_enabled():
            return
        print("\nLINKEDIN TRAVERSAL SUMMARY\n")
        print(f"pages_visited={self.pages_visited}")
        print(f"show_more_clicks={self.show_more_clicks}")
        print(f"scroll_cycles={self.scroll_cycles}")
        print(f"feed_growth_events={self.feed_growth_events}")
        print(f"feed_reset_events={self.feed_reset_events}")
        print(f"next_page_successes={self.next_page_successes}")
        print(f"next_page_failures={self.next_page_failures}")
        print(f"duplicate_cards_skipped={self.duplicate_cards_skipped}")
        print(f"jobs_accumulated={self.jobs_accumulated}")
        print(f"unique_v2_jobs={self.unique_v2_jobs}")
        print(
            f"show_more_growth_hits={self.show_more_growth_hits} "
            f"show_more_no_growth={self.show_more_no_growth} "
            f"reset_recovery_attempts={self.reset_recovery_attempts} "
            f"reset_aborts={self.reset_aborts}\n"
        )


class _LinkedInTraversalContext:
    """Tracks feed position / pagination to detect resets between continuation steps."""

    def __init__(self) -> None:
        self.last_url: str | None = None
        self.last_start: str | None = None
        self.peak_visible = 0
        self.last_first_job_id: str | None = None
        self.seen_page_first_ids: set[str] = set()
        self.consecutive_resets = 0

    def note_visible(self, count: int) -> None:
        self.peak_visible = max(self.peak_visible, count)

    def note_page_state(self, page) -> None:
        self.last_url = page.url
        self.last_start = _li_url_jobs_start_param(page.url)
        sig = _li_first_visible_job_card_signature(page)
        jid = sig.get("job_id")
        self.last_first_job_id = jid
        if jid:
            self.seen_page_first_ids.add(str(jid))


def _li_humanized_pause(
    page,
    ms_low: int,
    ms_high: int,
    metrics: _LinkedInTraversalMetrics | None = None,
    label: str = "normal",
) -> None:
    t = random.randint(ms_low, ms_high)
    if metrics is not None and random.random() < 0.14:
        t += random.randint(700, 2400)
        label = "think"
    _li_diag_log(f"linkedin_humanized_pause label={label} ms={t}", verbose=True)
    page.wait_for_timeout(t)


def _li_humanized_scroll(
    scroll_loc,
    page,
    metrics: _LinkedInTraversalMetrics | None = None,
) -> None:
    step = random.randint(1400, 2900)
    if scroll_loc is not None:
        scroll_loc.evaluate(
            """(el, step) => {
                const maxTop = Math.max(0, el.scrollHeight - el.clientHeight);
                el.scrollTop = Math.min(el.scrollTop + step, maxTop);
            }""",
            step,
        )
    else:
        wheel = random.randint(3200, 6800)
        page.mouse.wheel(0, wheel)
        step = wheel
    if metrics is not None:
        metrics.scroll_cycles += 1
    _li_diag_log(f"linkedin_humanized_scroll step_px={step}", verbose=True)


def _li_start_param_as_int(start_val) -> int | None:
    if start_val is None:
        return None
    try:
        return int(str(start_val).strip())
    except (TypeError, ValueError):
        return None


def _li_page_number_from_start(start_val) -> int:
    n = _li_start_param_as_int(start_val)
    if n is None:
        return 1
    return (n // 25) + 1


# In-feed lazy-load buttons (same results page).
_SHOW_MORE_SCOPED_CANDIDATES = [
    ("see_more_jobs", "button:has-text('See more jobs')"),
    ("show_more_jobs", "button:has-text('Show more jobs')"),
]

# Pagination next (distinct URL page) — classic LinkedIn jobs search only.
_NEXT_PAGE_SCOPED_CANDIDATES = [
    ("jobs_pagination_next", "button.jobs-search-pagination__button--next"),
    (
        "jobs_pagination_next_aria",
        "button.jobs-search-pagination__button[aria-label*='Next']",
    ),
    (
        "pagination_next_aria",
        "div.jobs-search-pagination button[aria-label*='Next'], "
        "nav.jobs-search-pagination button[aria-label*='Next'], "
        "section.jobs-search-pagination button[aria-label*='Next']",
    ),
]

# How You Fit / Top Applicant feed — React pagination (data-testid), qual URLs only.
_QUALIFICATION_NEXT_PAGE_CANDIDATES = [
    (
        "qual_pagination_next_visible",
        'button[data-testid="pagination-controls-next-button-visible"]',
    ),
    (
        "qual_pagination_next_testid",
        'button[data-testid*="pagination-controls-next-button"]',
    ),
    (
        "qual_pagination_next_testid_alt",
        'button[data-testid*="pagination-control-next-button"]',
    ),
]


def _li_next_page_candidates(url: str) -> list[tuple[str, str]]:
    """Candidate selectors for Next pagination; qual testids only on How You Fit URLs."""
    if _li_is_qualification_landing_url(url):
        return _QUALIFICATION_NEXT_PAGE_CANDIDATES + _NEXT_PAGE_SCOPED_CANDIDATES
    return _NEXT_PAGE_SCOPED_CANDIDATES


def _li_probe_next_button_state(
    jobs_root,
    *,
    candidates: list[tuple[str, str]] | None = None,
) -> dict:
    out = {
        "linkedin_next_button_detected": False,
        "linkedin_next_button_disabled": None,
    }
    if jobs_root is None:
        return out
    cands = candidates if candidates is not None else _NEXT_PAGE_SCOPED_CANDIDATES
    for _label, sel in cands:
        try:
            loc = jobs_root.locator(sel).first
            if loc.count() == 0 or not loc.is_visible():
                continue
            out["linkedin_next_button_detected"] = True
            disabled = loc.get_attribute("disabled")
            aria_dis = loc.get_attribute("aria-disabled")
            out["linkedin_next_button_disabled"] = bool(
                disabled is not None or (aria_dis or "").lower() == "true"
            )
            return out
        except Exception:
            continue
    return out


def _li_probe_next_button_state_page(page) -> dict:
    """Page-level Next probe (qualification landing fallback when jobs_root misses)."""
    return _li_probe_next_button_state(
        page, candidates=_li_next_page_candidates(page.url)
    )


def _li_log_qualification_pagination_diagnostics(
    page,
    jobs_root,
    jobs_root_desc: str | None,
) -> None:
    if not _li_is_qualification_landing_url(page.url):
        return
    candidates = _li_next_page_candidates(page.url)
    scoped = _li_probe_next_button_state(jobs_root, candidates=candidates)
    page_level = _li_probe_next_button_state(page, candidates=candidates)
    start = _li_url_jobs_start_param(page.url)
    _li_diag_log(
        "qualification_pagination_diag "
        f"cards={_li_count_job_cards(page)} "
        f"jobs_root={jobs_root_desc!r} "
        f"page_num={_li_page_number_from_start(start)} "
        f"scoped_next={scoped['linkedin_next_button_detected']} "
        f"scoped_next_disabled={scoped['linkedin_next_button_disabled']} "
        f"page_level_next={page_level['linkedin_next_button_detected']} "
        f"page_level_next_disabled={page_level['linkedin_next_button_disabled']}"
    )


def _li_probe_show_more_state(jobs_root) -> bool:
    if jobs_root is None:
        return False
    for _label, sel in _SHOW_MORE_SCOPED_CANDIDATES:
        try:
            loc = jobs_root.locator(sel).first
            if loc.count() > 0 and loc.is_visible():
                if _li_expansion_element_passes_exclusion(loc):
                    return True
        except Exception:
            continue
    return False


def _li_log_continuation_detection(
    page,
    jobs_root,
    metrics: _LinkedInTraversalMetrics,
    *,
    visible_before: int | None = None,
    visible_after: int | None = None,
    feed_growth: bool | None = None,
) -> None:
    show_more = _li_probe_show_more_state(jobs_root)
    next_state = _li_probe_next_button_state(jobs_root)
    if visible_before is not None:
        _li_diag_log(f"linkedin_visible_jobs_before_scroll={visible_before}", verbose=True)
    if visible_after is not None:
        _li_diag_log(f"linkedin_visible_jobs_after_scroll={visible_after}", verbose=True)
    if feed_growth is not None:
        if feed_growth:
            _li_diag_log(f"linkedin_feed_growth_detected={feed_growth}", verbose=True)
            metrics.feed_growth_events += 1
        else:
            _li_diag_log(f"linkedin_feed_growth_detected={feed_growth}", verbose=True)
    _li_diag_log(f"linkedin_show_more_detected={show_more}", verbose=True)
    _li_diag_log(
        f"linkedin_next_button_detected={next_state['linkedin_next_button_detected']}",
        verbose=True,
    )
    dis = next_state["linkedin_next_button_disabled"]
    if dis is not None:
        if dis:
            _li_diag_log(f"linkedin_next_button_disabled={dis}", verbose=True)
        else:
            _li_diag_log(f"linkedin_next_button_disabled={dis}", verbose=True)
    url = page.url
    start = _li_url_jobs_start_param(url)
    _li_diag_log(f"linkedin_url_snapshot={url[:280]!r}", verbose=True)
    _li_diag_log(
        f"linkedin_page_number_detected={_li_page_number_from_start(start)} start={start!r}",
        verbose=True,
    )


def _li_detect_feed_reset(
    page,
    ctx: _LinkedInTraversalContext,
    metrics: _LinkedInTraversalMetrics,
) -> bool:
    cur_start = _li_url_jobs_start_param(page.url)
    cur_count = _li_count_job_cards(page)
    sig = _li_first_visible_job_card_signature(page)
    cur_first = sig.get("job_id")

    reset = False
    prev_i = _li_start_param_as_int(ctx.last_start)
    cur_i = _li_start_param_as_int(cur_start)
    if prev_i is not None and cur_i is not None and cur_i < prev_i:
        reset = True
    if ctx.peak_visible > 0 and cur_count < ctx.peak_visible - 6:
        reset = True
    if (
        cur_first
        and ctx.last_first_job_id
        and str(cur_first) == str(ctx.last_first_job_id)
        and prev_i is not None
        and cur_i is not None
        and cur_i != prev_i
    ):
        reset = True

    if reset:
        _li_diag_log(f"linkedin_feed_reset_detected={reset}")
    else:
        _li_diag_log(f"linkedin_feed_reset_detected={reset}", verbose=True)
    if reset:
        metrics.feed_reset_events += 1
        ctx.consecutive_resets += 1
    else:
        ctx.consecutive_resets = 0
    return reset


def _li_find_scoped_control(page, jobs_root, candidates):
    if jobs_root is None:
        return None, None
    return _li_find_control_on_root(jobs_root, candidates)


def _li_find_page_level_control(page, candidates):
    return _li_find_control_on_root(page, candidates)


def _li_find_control_on_root(root, candidates):
    for label, sel in candidates:
        try:
            loc = root.locator(sel).first
            if loc.count() == 0 or not loc.is_visible():
                continue
            if not _li_expansion_element_passes_exclusion(loc):
                continue
            return loc, label
        except Exception:
            continue
    return None, None


# Strictly job-results–scoped: most specific LinkedIn jobs pagination first.
# No page-wide "Show more" / "Next" (filters, sidebars, dialogs).
_EXPANSION_SCOPED_CANDIDATES = [
    ("jobs_pagination_next", "button.jobs-search-pagination__button--next"),
    (
        "jobs_pagination_next_aria",
        "button.jobs-search-pagination__button[aria-label*='Next']",
    ),
    ("see_more_jobs", "button:has-text('See more jobs')"),
    ("show_more_jobs", "button:has-text('Show more jobs')"),
    (
        "pagination_show_more",
        "div.jobs-search-pagination button:has-text('Show more'), "
        "nav.jobs-search-pagination button:has-text('Show more'), "
        "section.jobs-search-pagination button:has-text('Show more')",
    ),
    (
        "pagination_next_aria",
        "div.jobs-search-pagination button[aria-label*='Next'], "
        "nav.jobs-search-pagination button[aria-label*='Next'], "
        "section.jobs-search-pagination button[aria-label*='Next']",
    ),
]

_INNER_LIST_BOTTOM_THRESHOLD_PX = 200
_INNER_LIST_BOTTOM_MAX_NUDGES = 8


def _li_inner_list_bottom_metrics(scroll_loc):
    """Metrics for the inner jobs list scroller, or None if unavailable."""
    if scroll_loc is None:
        return None
    try:
        return scroll_loc.evaluate(
            """el => {
                const st = el.scrollTop;
                const sh = el.scrollHeight;
                const ch = el.clientHeight;
                const maxScroll = Math.max(0, sh - ch);
                return {
                    scrollTop: st,
                    scrollHeight: sh,
                    clientHeight: ch,
                    distance_to_bottom: Math.max(0, maxScroll - st),
                };
            }"""
        )
    except Exception:
        return None


def _li_nudge_inner_scroll_if_far_from_bottom(
    page, scroll_loc, threshold: int, max_nudges: int
) -> None:
    """If the inner list is not near the bottom, scroll it before expansion clicks."""
    for i in range(max_nudges):
        m = _li_inner_list_bottom_metrics(scroll_loc)
        if not m:
            _li_diag_log(
                "inner_list_bottom_proximity nudge_skipped "
                "reason=scroll_loc_none_or_metrics_failed"
            , verbose=True)
            return
        dtb = float(m.get("distance_to_bottom") or 0)
        _li_diag_log(
            f"inner_list_bottom_proximity nudge_iter={i + 1}/{max_nudges} "
            f"scrollTop={m.get('scrollTop')} scrollHeight={m.get('scrollHeight')} "
            f"clientHeight={m.get('clientHeight')} distance_to_bottom={dtb} "
            f"threshold={threshold}"
        , verbose=True)
        if dtb <= threshold:
            return
        _li_scroll_inner_or_fallback(scroll_loc, page)
        _li_human_pause(page, 400, 900)


def _li_clear_expansion_root_harness(page) -> None:
    try:
        page.evaluate(
            """() => {
                document.querySelectorAll('[data-li-expansion-root]').forEach((e) => {
                    e.removeAttribute('data-li-expansion-root');
                });
            }"""
        )
    except Exception:
        pass


def _li_get_jobs_expansion_root(page):
    """
    Locator for the jobs results pane / list subtree that contains job cards.
    Prefer a pane that includes jobs-search-pagination as a descendant when possible.
    """
    _li_clear_expansion_root_harness(page)

    card_loc = (
        _li_job_card_locator(page)
        if _li_is_qualification_landing_url(page.url)
        else page.locator(_CARD_SELECTOR)
    )

    try:
        pane = (
            page.locator("div.jobs-search-results")
            .filter(has=card_loc)
            .first
        )
        if pane.count() > 0 and pane.is_visible():
            return pane, "jobs_search_results:has(cards)"
    except Exception as e:
        _li_diag_log(f"jobs_expansion_root_pane_err={e!r}", verbose=True)

    if _li_is_qualification_landing_url(page.url):
        try:
            pane = page.locator("main").filter(has=card_loc).first
            if pane.count() > 0 and pane.is_visible():
                return pane, "main:has(qualification_cards)"
        except Exception as e:
            _li_diag_log(f"jobs_expansion_root_qualification_err={e!r}", verbose=True)

    for label, sel in (
        ("jobs_search_two_pane_results", "div.jobs-search-two-pane__results"),
        ("jobs_search_results_list", "div.jobs-search-results-list"),
        ("scaffold_layout_list", "div.scaffold-layout__list"),
    ):
        try:
            loc = page.locator(sel).filter(has=card_loc).first
            if loc.count() == 0:
                continue
            if loc.is_visible():
                return loc, f"{label}:{sel}"
        except Exception as e:
            _li_diag_log(f"jobs_expansion_root_probe_err {label} err={e!r}", verbose=True)
            continue

    try:
        js = page.evaluate(
            """() => {
                const item = document.querySelector('li.scaffold-layout__list-item');
                if (!item) return { ok: false, reason: 'no_list_items' };
                let el = item.parentElement;
                while (el && el !== document.body) {
                    const cls = String(el.className || '');
                    if (
                        cls.includes('jobs-search-results') &&
                        cls.includes('jobs-search') &&
                        !cls.includes('jobs-search-filters')
                    ) {
                        el.setAttribute('data-li-expansion-root', '1');
                        return { ok: true, reason: 'ancestor_jobs_search_results' };
                    }
                    el = el.parentElement;
                }
                el = item.parentElement;
                while (el && el !== document.body) {
                    const cls = String(el.className || '');
                    if (
                        cls.includes('jobs-search-results-list') ||
                        cls.includes('scaffold-layout__list')
                    ) {
                        el.setAttribute('data-li-expansion-root', '1');
                        return { ok: true, reason: 'ancestor_list' };
                    }
                    el = el.parentElement;
                }
                return { ok: false, reason: 'no_suitable_ancestor' };
            }"""
        )
        if js and js.get("ok"):
            rloc = page.locator("[data-li-expansion-root='1']").first
            if rloc.count() > 0 and rloc.is_visible():
                return rloc, f"data-li-expansion-root:{js.get('reason')}"
    except Exception as e:
        _li_diag_log(f"jobs_expansion_root_js_err={e!r}", verbose=True)

    return None, None


def _li_expansion_element_passes_exclusion(ctrl) -> bool:
    """Reject controls inside dialogs, filter panels, or obvious non-results chrome."""
    try:
        return ctrl.evaluate(
            """el => {
                let n = el;
                for (let i = 0; i < 14 && n; i++) {
                    const r = n.getAttribute && n.getAttribute('role');
                    if (r === 'dialog') return false;
                    const c = String(n.className || '');
                    if (c.includes('jobs-search-filters')) return false;
                    if (c.includes('search-filters') && c.includes('panel')) return false;
                    if (c.includes('facets-edit')) return false;
                    if (c.includes('show-more-filters')) return false;
                    n = n.parentElement;
                }
                return true;
            }"""
        )
    except Exception:
        return False


def _li_log_expansion_preclick_diagnostics(ctrl, scroll_loc, page) -> None:
    """Bottom proximity on inner scroller + control identity for PM-facing logs."""
    m = _li_inner_list_bottom_metrics(scroll_loc)
    if m is not None:
        dtb = float(m.get("distance_to_bottom") or 0)
        _li_diag_log(
            "inner_list_bottom_proximity pre_click "
            f"scrollTop={m.get('scrollTop')} scrollHeight={m.get('scrollHeight')} "
            f"clientHeight={m.get('clientHeight')} distance_to_bottom={dtb}"
        , verbose=True)
    else:
        _li_diag_log(
            "inner_list_bottom_proximity pre_click scroll_loc=None_or_metrics_failed"
        , verbose=True)

    try:
        box = ctrl.bounding_box()
        text = (ctrl.inner_text() or "").strip()
        if len(text) > 240:
            text = text[:240] + "…"
        html = ctrl.evaluate("el => (el.outerHTML || '').slice(0, 520)")
        dom_path = ctrl.evaluate(
            """el => {
                const parts = [];
                let n = el;
                for (let depth = 0; depth < 12 && n && n.nodeType === 1; depth++) {
                    let s = n.tagName.toLowerCase();
                    if (n.id) s += '#' + n.id;
                    const cls = String(n.className || '')
                        .split(/\\s+/)
                        .filter(Boolean)
                        .slice(0, 4)
                        .join('.');
                    if (cls) s += '.' + cls;
                    parts.unshift(s);
                    n = n.parentElement;
                }
                return parts.join(' > ');
            }"""
        )
        _li_diag_log(f"expansion_control_text={text!r}", verbose=True)
        _li_diag_log(f"expansion_control_outer_html={html!r}", verbose=True)
        _li_diag_log(f"expansion_control_bounding_box={box!r}", verbose=True)
        _li_diag_log(f"expansion_control_dom_path={dom_path!r}", verbose=True)
    except Exception as e:
        _li_diag_log(f"expansion_control_diagnostics_err={e!r}", verbose=True)


def _li_prepare_expansion_control_for_click(ctrl, page) -> bool:
    """Scroll into view; require visible and enabled before click."""
    try:
        ctrl.scroll_into_view_if_needed(timeout=12000)
        _li_human_pause(page, 200, 550)
        if not ctrl.is_visible():
            _li_diag_log(
                "expansion_control_preclick_abort reason=not_visible_after_scroll_into_view"
            , verbose=True)
            return False
        disabled = ctrl.get_attribute("disabled")
        aria_dis = ctrl.get_attribute("aria-disabled")
        if disabled is not None or (aria_dis or "").lower() == "true":
            _li_diag_log(
                "expansion_control_preclick_abort reason=disabled_or_aria_disabled "
                f"disabled_attr={disabled!r} aria-disabled={aria_dis!r}"
            , verbose=True)
            return False
        return True
    except Exception as e:
        _li_diag_log(f"expansion_control_preclick_prepare_err={e!r}", verbose=True)
        return False


def _li_find_visible_expansion_control(page, jobs_root):
    """
    First visible expansion control under jobs_root only, or (None, None).
    Does not click. Strict: no jobs_root => no expansion click candidates.
    """
    if jobs_root is None:
        _li_diag_log(
            "expansion_control_search_abort reason=no_jobs_expansion_root_strict_scope"
        , verbose=True)
        return None, None

    for label, sel in _EXPANSION_SCOPED_CANDIDATES:
        try:
            loc = jobs_root.locator(sel).first
            if loc.count() == 0:
                continue
            if not loc.is_visible():
                continue
            if not _li_expansion_element_passes_exclusion(loc):
                _li_diag_log(
                    f"expansion_candidate_rejected label={label!r} reason=exclusion_walk"
                , verbose=True)
                continue
            return loc, label
        except Exception as e:
            _li_diag_log(
                f"expansion_locator_probe_err label={label!r} sel={sel!r} err={e!r}"
            , verbose=True)
            continue
    return None, None


def _li_try_show_more_in_feed(
    page,
    jobs_root,
    scroll_loc,
    metrics: _LinkedInTraversalMetrics,
    trav_ctx: _LinkedInTraversalContext,
) -> bool:
    """
    Phase 2: click in-feed See/Show more jobs when visible; return True if visible count grew.
    """
    if metrics.show_more_clicks >= _LINKEDIN_MAX_SHOW_MORE_CLICKS:
        return False

    ctrl, clabel = _li_find_scoped_control(page, jobs_root, _SHOW_MORE_SCOPED_CANDIDATES)
    if ctrl is None:
        return False

    before = _li_count_job_cards(page)
    url_before = page.url
    _li_log_continuation_detection(
        page, jobs_root, metrics, visible_before=before, feed_growth=None
    )

    if not _li_prepare_expansion_control_for_click(ctrl, page):
        return False

    _li_humanized_pause(page, 900, 2200, metrics, "pre_click")
    metrics.show_more_clicks += 1
    _li_diag_log(f"linkedin_show_more_clicks={metrics.show_more_clicks} label={clabel!r}", verbose=True)

    try:
        ctrl.click(timeout=10000)
    except Exception as e:
        _li_diag_log(f"linkedin_show_more_click_failed err={e!r}")
        metrics.show_more_no_growth += 1
        return False

    _li_humanized_pause(page, 1600, 3400, metrics, "post_click")
    after = _li_count_job_cards(page)
    grew = after > before and page.url == url_before
    _li_log_continuation_detection(
        page,
        jobs_root,
        metrics,
        visible_before=before,
        visible_after=after,
        feed_growth=grew,
    )
    trav_ctx.note_visible(after)

    if grew:
        metrics.show_more_growth_hits += 1
        _li_diag_log(f"linkedin_show_more_growth_hits={metrics.show_more_growth_hits}")
        return True

    metrics.show_more_no_growth += 1
    _li_diag_log(f"linkedin_show_more_no_growth={metrics.show_more_no_growth}")
    return False


def _li_try_next_page_transition(
    page,
    jobs_root,
    scroll_loc,
    scroll_loc_desc: str,
    metrics: _LinkedInTraversalMetrics,
    trav_ctx: _LinkedInTraversalContext,
    *,
    jobs_root_desc: str | None = None,
) -> tuple[bool, object, str, object]:
    """
    Phase 3: Next-page pagination using existing hydration (unchanged).
    Returns (success, scroll_loc, scroll_desc, jobs_root).
    """
    scoped_state = _li_probe_next_button_state(
        jobs_root, candidates=_li_next_page_candidates(page.url)
    )
    qual_landing = _li_is_qualification_landing_url(page.url)
    page_state = (
        _li_probe_next_button_state(
            page, candidates=_li_next_page_candidates(page.url)
        )
        if qual_landing
        else scoped_state
    )
    use_page_level = (
        qual_landing
        and not scoped_state["linkedin_next_button_detected"]
        and page_state["linkedin_next_button_detected"]
    )
    next_state = page_state if use_page_level else scoped_state
    next_scope = "page_level" if use_page_level else "jobs_root"

    if qual_landing:
        _li_log_qualification_pagination_diagnostics(page, jobs_root, jobs_root_desc)

    if not next_state["linkedin_next_button_detected"]:
        _li_diag_log(
            "expansion_control_detected=false reason=no_next_button "
            f"scoped={scoped_state['linkedin_next_button_detected']} "
            f"page_level={page_state['linkedin_next_button_detected']}",
            verbose=True,
        )
        return False, scroll_loc, scroll_loc_desc, jobs_root
    if next_state["linkedin_next_button_disabled"]:
        _li_diag_log(
            f"linkedin_next_page_click=skipped reason=next_disabled scope={next_scope}"
        )
        return False, scroll_loc, scroll_loc_desc, jobs_root

    _li_nudge_inner_scroll_if_far_from_bottom(
        page,
        scroll_loc,
        threshold=_INNER_LIST_BOTTOM_THRESHOLD_PX,
        max_nudges=_INNER_LIST_BOTTOM_MAX_NUDGES,
    )

    next_candidates = _li_next_page_candidates(page.url)
    if use_page_level:
        ctrl, clabel = _li_find_page_level_control(page, next_candidates)
    else:
        ctrl, clabel = _li_find_scoped_control(
            page, jobs_root, next_candidates
        )
    if ctrl is None:
        return False, scroll_loc, scroll_loc_desc, jobs_root

    cur = _li_count_job_cards(page)
    _li_diag_log(
        f"expansion_control_detected=true label={clabel!r} scope={next_scope}",
        verbose=True,
    )
    _li_log_expansion_preclick_diagnostics(ctrl, scroll_loc, page)

    if not _li_prepare_expansion_control_for_click(ctrl, page):
        return False, scroll_loc, scroll_loc_desc, jobs_root

    pre_click_url = page.url
    pre_click_start = _li_url_jobs_start_param(pre_click_url)
    pre_sig = _li_first_visible_job_card_signature(page)
    pre_fingerprint = (
        pre_sig.get("job_id"),
        (pre_sig.get("title_text") or "")[:120],
        (pre_sig.get("raw_card_text") or "")[:160],
    )
    pre_count = cur
    _li_diag_log(
        "pre_expansion_click_snapshot "
        f"url={pre_click_url[:260]!r} start={pre_click_start!r} "
        f"first_card_job_id={pre_sig.get('job_id')!r} "
        f"first_card_text={pre_sig.get('title_text')!r}"
    , verbose=True)

    _li_humanized_pause(page, 1200, 2600, metrics, "pre_click")
    _li_humanized_pause(page, 250, 900, metrics, "pre_click")

    _li_diag_log(f"linkedin_next_page_click=true control={clabel!r} scope={next_scope}")
    try:
        ctrl.click(timeout=10000)
        _li_diag_log("expansion_click_success")
    except Exception as e:
        _li_diag_log(f"expansion_click_failed err={e!r}")
        return False, scroll_loc, scroll_loc_desc, jobs_root

    _li_humanized_pause(page, 1800, 3600, metrics, "post_click")
    try:
        page.wait_for_load_state("domcontentloaded", timeout=8000)
    except Exception as e:
        _li_diag_log(f"post_expansion_domcontentloaded_wait_skipped err={e!r}", verbose=True)

    hydr = _li_wait_post_expansion_hydration(
        page,
        pre_click_url=pre_click_url,
        pre_click_start=pre_click_start,
        pre_fingerprint=pre_fingerprint,
        pre_count=pre_count,
        timeout_ms=28000,
    )

    post_url = hydr.get("post_pagination_url") or page.url
    _li_diag_log(f"post_pagination_url={post_url[:320]!r}")

    fs = hydr.get("first_sig_after") or {}
    _li_diag_log(f"post_pagination_first_card_id={fs.get('job_id')!r}", verbose=True)
    _li_diag_log(f"post_pagination_first_card_text={fs.get('title_text')!r}", verbose=True)
    _li_diag_log(
        f"card_dom_refresh_detected={bool(hydr.get('card_dom_refresh_detected'))}"
    )

    new_c = int(hydr.get("card_count_after_refresh") or -1)
    _li_diag_log(f"card_count_after_refresh={new_c}", verbose=True)
    _li_diag_log(f"expansion_post_wait_cards={new_c}", verbose=True)

    dom_ok = bool(hydr.get("card_dom_refresh_detected"))
    numeric_growth = new_c > cur
    url_changed = pre_click_url != post_url
    start_after = _li_url_jobs_start_param(post_url)
    page_transition = dom_ok or (
        url_changed
        and str(pre_click_start or "") != str(start_after or "")
    )

    if page_transition:
        _li_diag_log("linkedin_page_transition_detected=true")
        _li_diag_log(
            f"linkedin_page_number_detected={_li_page_number_from_start(start_after)}"
        , verbose=True)
        if qual_landing:
            _li_diag_log(
                "qualification_pagination_completed "
                f"scope={next_scope} page_num={_li_page_number_from_start(start_after)} "
                f"cards={new_c}"
            )
        _li_diag_log("expansion_growth_detected")

        active_scroll_loc, active_scroll_desc = _li_find_inner_jobs_scroll_locator(page)
        if active_scroll_loc is not None:
            _li_diag_log(
                "post_pagination_reacquired_inner_scroll "
                f"selector={active_scroll_desc!r}"
            , verbose=True)
        else:
            _li_diag_log(
                f"post_pagination_reacquired_inner_scroll selector={active_scroll_desc!r} "
                "(page.mouse.wheel fallback)"
            , verbose=True)

        jobs_root, jobs_root_desc = _li_get_jobs_expansion_root(page)
        if jobs_root is None:
            _li_diag_log("jobs_expansion_root_reacquire_failed after_page_transition", verbose=True)
        else:
            _li_diag_log(f"jobs_expansion_root_reacquired desc={jobs_root_desc!r}", verbose=True)

        trav_ctx.note_page_state(page)
        return True, active_scroll_loc, active_scroll_desc, jobs_root

    _li_diag_log("linkedin_next_page_no_growth=true")
    _li_diag_log("expansion_no_growth")
    return False, scroll_loc, scroll_loc_desc, jobs_root


def _li_orchestrate_expansion_then_resume_traversal(
    page,
    scroll_loc,
    scroll_loc_desc: str,
    summ: dict,
    on_post_pagination_dom_settled=None,
    metrics: _LinkedInTraversalMetrics | None = None,
    trav_ctx: _LinkedInTraversalContext | None = None,
) -> dict:
    """
    Mature continuation loop: in-feed show-more attempts, then true next-page traversal.
    Hydration after Next is unchanged; accumulation callbacks run after each settled page.
    """
    if metrics is None:
        metrics = _LinkedInTraversalMetrics()
    if trav_ctx is None:
        trav_ctx = _LinkedInTraversalContext()

    summ_out = summ
    active_scroll_loc = scroll_loc
    active_scroll_desc = scroll_loc_desc

    jobs_root, jobs_root_desc = _li_get_jobs_expansion_root(page)
    if jobs_root is None:
        _li_diag_log("jobs_expansion_root unresolved strict_expansion_scope_unavailable")
    else:
        _li_diag_log(f"jobs_expansion_root_resolved desc={jobs_root_desc!r}", verbose=True)

    if metrics.pages_visited < 1:
        metrics.pages_visited = 1
    trav_ctx.note_page_state(page)
    trav_ctx.note_visible(_li_count_job_cards(page))

    show_more_no_growth_streak = 0

    while metrics.pages_visited < _LINKEDIN_MAX_NEXT_PAGES:
        _li_log_continuation_detection(page, jobs_root, metrics)

        if _li_detect_feed_reset(page, trav_ctx, metrics):
            if trav_ctx.consecutive_resets >= _LINKEDIN_RESET_ABORT_THRESHOLD:
                metrics.reset_aborts += 1
                _li_diag_log("linkedin_reset_abort=true")
                break
            metrics.reset_recovery_attempts += 1
            _li_diag_log("linkedin_reset_recovery_attempt=1")
            _li_humanized_pause(page, 1400, 3200, metrics, "recovery")
            jobs_root, jobs_root_desc = _li_get_jobs_expansion_root(page)
            continue

        grew_show_more = _li_try_show_more_in_feed(
            page, jobs_root, active_scroll_loc, metrics, trav_ctx
        )
        if grew_show_more:
            show_more_no_growth_streak = 0
            summ_out = _li_adaptive_scroll_traversal(
                page,
                active_scroll_loc,
                active_scroll_desc,
                metrics=metrics,
                trav_ctx=trav_ctx,
            )
            if on_post_pagination_dom_settled is not None:
                try:
                    on_post_pagination_dom_settled(
                        page,
                        f"after_show_more_{metrics.show_more_growth_hits}",
                    )
                except Exception as e:
                    _li_diag_log(f"on_post_pagination_dom_settled_err err={e!r}")
            jobs_root, jobs_root_desc = _li_get_jobs_expansion_root(page)
            trav_ctx.note_page_state(page)
            continue

        show_more_no_growth_streak += 1
        if (
            show_more_no_growth_streak >= _LINKEDIN_SHOW_MORE_NO_GROWTH_STOP
            and not _li_probe_show_more_state(jobs_root)
        ):
            pass
        elif show_more_no_growth_streak < _LINKEDIN_SHOW_MORE_NO_GROWTH_STOP:
            if _li_probe_show_more_state(jobs_root):
                continue

        ok, active_scroll_loc, active_scroll_desc, jobs_root = _li_try_next_page_transition(
            page,
            jobs_root,
            active_scroll_loc,
            active_scroll_desc,
            metrics,
            trav_ctx,
            jobs_root_desc=jobs_root_desc,
        )
        if not ok:
            metrics.next_page_failures += 1
            break

        metrics.next_page_successes += 1
        metrics.pages_visited += 1
        _li_diag_log(f"linkedin_next_page_success={metrics.next_page_successes}")

        summ_out = _li_adaptive_scroll_traversal(
            page,
            active_scroll_loc,
            active_scroll_desc,
            metrics=metrics,
            trav_ctx=trav_ctx,
        )
        if on_post_pagination_dom_settled is not None:
            try:
                on_post_pagination_dom_settled(
                    page, f"after_pagination_attempt_{metrics.next_page_successes}"
                )
            except Exception as e:
                _li_diag_log(
                    f"on_post_pagination_dom_settled_err attempt={metrics.next_page_successes} "
                    f"err={e!r}"
                )
        trav_ctx.note_page_state(page)
        show_more_no_growth_streak = 0

    return summ_out


# LinkedIn jobs list — try stable-ish containers first, then scrollable ancestor harness.
_INNER_JOBS_SCROLL_SELECTORS = [
    "div.jobs-search-results-list",
    "div.jobs-search-results__list",
    "div.scaffold-layout__list",
    "div[class*='jobs-search-results-list']",
    "div.jobs-search-results",
]


def _li_clear_scroll_harness(page) -> None:
    try:
        page.evaluate(
            """() => {
                document.querySelectorAll('[data-li-scroll-harness]').forEach((e) => {
                    e.removeAttribute('data-li-scroll-harness');
                });
            }"""
        )
    except Exception:
        pass


def _li_find_inner_jobs_scroll_locator(page):
    """
    Returns (locator | None, description_string) for the vertical jobs list scroller.
    """
    _li_clear_scroll_harness(page)

    for sel in _INNER_JOBS_SCROLL_SELECTORS:
        try:
            loc = page.locator(sel).first
            if loc.count() == 0:
                continue
            scrollable = loc.evaluate(
                """el => {
                    const sh = el.scrollHeight;
                    const ch = el.clientHeight;
                    return sh > ch + 20;
                }"""
            )
            if scrollable:
                return loc, sel
        except Exception as e:
            _li_diag_log(f"inner_scroll_probe_selector_failed sel={sel!r} err={e!r}", verbose=True)
            continue

    res = page.evaluate(
        """() => {
            const item = document.querySelector('li.scaffold-layout__list-item');
            if (!item) return { ok: false, reason: 'no_list_items' };
            let el = item.parentElement;
            while (el && el !== document.documentElement) {
                const sh = el.scrollHeight;
                const ch = el.clientHeight;
                if (sh > ch + 15) {
                    el.setAttribute('data-li-scroll-harness', '1');
                    return {
                        ok: true,
                        reason: 'scrollable_ancestor',
                        className: String(el.className || '').slice(0, 180),
                        tag: el.tagName,
                    };
                }
                el = el.parentElement;
            }
            return { ok: false, reason: 'no_scrollable_ancestor' };
        }"""
    )
    if res and res.get("ok"):
        loc = page.locator("[data-li-scroll-harness='1']").first
        desc = (
            f"data-li-scroll-harness ancestor tag={res.get('tag')} "
            f"class={res.get('className', '')!r}"
        )
        return loc, desc

    reason = (res or {}).get("reason", "unknown")
    _li_diag_log(f"inner_scroll_container_not_found reason={reason!r}")
    return None, f"fallback_mouse_wheel reason={reason}"


def _li_scroll_inner_or_fallback(scroll_loc, page) -> None:
    """Scroll the jobs list container, or fall back to page wheel (last resort)."""
    if scroll_loc is not None:
        scroll_loc.evaluate(
            """el => {
                const step = 2200;
                const maxTop = Math.max(0, el.scrollHeight - el.clientHeight);
                el.scrollTop = Math.min(el.scrollTop + step, maxTop);
            }"""
        )
    else:
        page.mouse.wheel(0, 5000)


def _li_adaptive_scroll_traversal(
    page,
    scroll_loc,
    scroll_loc_desc: str,
    metrics: _LinkedInTraversalMetrics | None = None,
    trav_ctx: _LinkedInTraversalContext | None = None,
) -> dict:
    """
    Scroll until card count stabilizes or safety cap.
    Returns diagnostic summary dict.
    """
    stabilization_target = 3
    max_iters = 80

    prev = _li_count_job_cards(page)
    max_seen = prev
    stab = 0
    exit_reason = ""
    if trav_ctx is not None:
        trav_ctx.note_visible(prev)

    _li_diag_log(
        f"adaptive_scroll_start initial_cards={prev} "
        f"stabilization_rounds={stabilization_target} max_iters={max_iters}",
        verbose=True,
    )

    for ai in range(max_iters):
        probe_b = _li_scroll_probe(page)
        url_b = page.url
        before_scroll = prev

        if metrics is not None:
            _li_humanized_scroll(scroll_loc, page, metrics)
            _li_humanized_pause(page, 1000, 1800, metrics, "scroll")
        else:
            _li_scroll_inner_or_fallback(scroll_loc, page)
            wait_ms = random.randint(1000, 1600)
            page.wait_for_timeout(wait_ms)

        cur = _li_count_job_cards(page)
        max_seen = max(max_seen, cur)
        if trav_ctx is not None:
            trav_ctx.note_visible(cur)
        probe_a = _li_scroll_probe(page)
        url_a = page.url

        if metrics is not None:
            _li_log_continuation_detection(
                page,
                None,
                metrics,
                visible_before=before_scroll,
                visible_after=cur,
                feed_growth=(cur > before_scroll),
            )

        if cur > prev:
            _li_diag_log(
                f"adaptive_scroll_iter={ai + 1}/{max_iters} card_growth old={prev} new={cur} "
                f"url_changed={(url_b != url_a)}",
                verbose=True,
            )
            stab = 0
        else:
            stab += 1
            _li_diag_log(
                f"adaptive_scroll_iter={ai + 1}/{max_iters} no_growth cards={cur} "
                f"stabilization_counter={stab}/{stabilization_target}",
                verbose=True,
            )

        _li_log_scroll_top_deltas(probe_b, probe_a, ai + 1)

        prev = cur

        if stab >= stabilization_target:
            exit_reason = f"stabilized_no_growth_for_{stabilization_target}_consecutive_iterations"
            break

    if not exit_reason:
        exit_reason = "max_iterations_safety_cap"

    _li_diag_log(
        f"traversal_complete exit_reason={exit_reason} final_cards={prev} "
        f"max_cards_seen={max_seen} card_count_exceeded_25={max_seen > 25}"
    )

    return {
        "final_cards": prev,
        "max_cards_seen": max_seen,
        "exit_reason": exit_reason,
        "scroll_loc_desc": scroll_loc_desc,
    }


def _li_scrape_qualification_landing_cards_into(
    page,
    jobs: list,
    processed_job_ids: set[str],
    seen_job_key_v2: set[str],
    dom_pass_label: str,
    metrics: _LinkedInTraversalMetrics | None = None,
) -> None:
    """Scrape How You Fit / search-results list rows (role=button cards)."""
    loc = _li_job_card_locator(page)
    n_cards = loc.count()
    _li_diag_log(
        f"linkedin_qualification_dom_pass label={dom_pass_label!r} list_rows={n_cards} "
        f"accumulated_jobs_before_pass={len(jobs)}",
        verbose=True,
    )
    appended_this_pass = 0
    excluded_keywords = [
        "intern",
        "analyst",
        "consultant",
        "designer",
        "principal",
        "staff",
        "director",
        "head",
        "chief",
        "vp",
        "vice president",
    ]

    for idx in range(n_cards):
        card = loc.nth(idx)
        try:
            card_text = (card.inner_text() or "").strip()
            title, company, location, time_posted = _li_parse_qualification_card_text(
                card_text
            )
            title_lower = title.lower()
            if any(x in title_lower for x in excluded_keywords):
                continue

            card.click()
            if metrics is not None:
                _li_humanized_pause(page, 1400, 3200, metrics, "qual_card_click")
            else:
                _li_human_pause(page, 1400, 3200)
            job_id = _li_url_current_job_id(page.url)
            if job_id and job_id in processed_job_ids:
                if metrics is not None:
                    metrics.duplicate_cards_skipped += 1
                continue
            if job_id:
                processed_job_ids.add(job_id)

            pt_title, pt_company = _li_title_company_from_page_title(page.title())
            if pt_title:
                title = pt_title
            if pt_company:
                company = pt_company

            posted_from_page = _li_extract_time_posted_from_page(page)
            if posted_from_page != "Unknown":
                time_posted = posted_from_page

            hiring_manager = _li_extract_hiring_manager_from_page(page)

            link = (
                f"https://www.linkedin.com/jobs/view/{job_id}/"
                if job_id
                else page.url
            )

            job_data = {
                "title": title,
                "company": company,
                "location": location.replace("Bengaluru", "Bangalore"),
                "link": link,
                "source": "linkedin",
                "time_posted": time_posted,
                "applied": False,
                "hiring_manager": hiring_manager,
                "score": 0,
            }

            if any(x in title.lower() for x in excluded_keywords):
                continue

            v2k, _v2_src = generate_job_key_v2(job_data)
            if v2k in seen_job_key_v2:
                if metrics is not None:
                    metrics.duplicate_cards_skipped += 1
                continue
            seen_job_key_v2.add(v2k)
            jobs.append(job_data)
            appended_this_pass += 1
        except Exception as e:
            _li_diag_log(
                f"qualification_card_index={idx} pass={dom_pass_label!r} err={e!r}",
                verbose=True,
            )

    _li_diag_log(
        f"linkedin_qualification_dom_pass_done label={dom_pass_label!r} "
        f"appended_this_pass={appended_this_pass} jobs_total={len(jobs)}",
        verbose=True,
    )


def _li_scrape_visible_job_cards_into(
    page,
    jobs: list,
    processed_job_ids: set[str],
    seen_job_key_v2: set[str],
    dom_pass_label: str,
    nav_state: dict,
    metrics: _LinkedInTraversalMetrics | None = None,
) -> None:
    """
    Read the current jobs search list DOM and append structured jobs into ``jobs``.

    Invoked after the initial adaptive scroll (page 1) and again after each
    successful pagination + adaptive pass so listings accumulate instead of only
    the final SPA snapshot. Dedup uses ``generate_job_key_v2`` (JOB_KEY_V2).
    """
    if _li_is_qualification_landing_url(page.url):
        _li_scrape_qualification_landing_cards_into(
            page,
            jobs,
            processed_job_ids,
            seen_job_key_v2,
            dom_pass_label,
            metrics=metrics,
        )
        return

    job_cards = page.query_selector_all(_CARD_SELECTOR)
    _li_diag_log(
        f"linkedin_list_dom_pass label={dom_pass_label!r} list_rows={len(job_cards)} "
        f"accumulated_jobs_before_pass={len(jobs)} "
        f"v2_keys_tracked={len(seen_job_key_v2)}",
        verbose=True,
    )
    appended_this_pass = 0

    for idx, job in enumerate(job_cards):
        try:
            title_elem = (
                job.query_selector("a.job-card-list__title--link strong")
                or job.query_selector("a.job-card-list__title--link span")
                or job.query_selector("a.job-card-list__title--link")
                or job.query_selector("a span[aria-hidden='true']")
            )

            company_elem = job.query_selector(
                ".artdeco-entity-lockup__subtitle span"
            )

            location_elem = job.query_selector(
                ".artdeco-entity-lockup__caption"
            )

            if not title_elem:
                _li_diag_log(
                    f"card_index={idx} pass={dom_pass_label!r} "
                    f"title_selector_failed (skipping card)"
                , verbose=True)
                continue

            title = title_elem.inner_text().strip()
            title_lower = title.lower()

            if any(
                x in title_lower
                for x in [
                    "intern",
                    "analyst",
                    "consultant",
                    "designer",
                    "principal",
                    "staff",
                    "director",
                    "head",
                    "chief",
                    "vp",
                    "vice president",
                ]
            ):
                continue

            link_elem_early = job.query_selector("a")
            raw_early = (
                link_elem_early.get_attribute("href")
                if link_elem_early
                else None
            )
            job_id_early = None
            if raw_early and "/jobs/view/" in raw_early:
                job_id_early = raw_early.split("/jobs/view/")[1].split("/")[0]
            if job_id_early and job_id_early in processed_job_ids:
                if metrics is not None:
                    metrics.duplicate_cards_skipped += 1
                _li_diag_log(
                    f"card_index={idx} pass={dom_pass_label!r} "
                    f"skip_duplicate_traversal_job_id={job_id_early}"
                , verbose=True)
                continue
            if job_id_early:
                processed_job_ids.add(job_id_early)

            job.click()
            page.wait_for_timeout(2000)
            _li_diag_log(
                f"card_index={idx} pass={dom_pass_label!r} post_click url={page.url[:240]}"
            , verbose=True)

            time_posted = _li_extract_time_posted_from_page(page)
            if time_posted != "Unknown":
                _li_diag_log(
                    f"card_index={idx} pass={dom_pass_label!r} time_posted={time_posted!r}",
                    verbose=True,
                )

            applied = False

            try:
                applied_elem = page.query_selector(
                    "span.jobs-s-apply__application-status-text"
                )

                if applied_elem:
                    applied_text = applied_elem.inner_text().lower()
                    if "applied" in applied_text:
                        applied = True
            except Exception as e:
                _li_diag_log(
                    f"card_index={idx} pass={dom_pass_label!r} applied_status_read_failed: {e!r}"
                , verbose=True)

            hiring_manager = _li_extract_hiring_manager_from_page(page)
            if hiring_manager != _LI_NOT_SPECIFIED_HM:
                print(f"✅ Hiring Manager Found: {hiring_manager}")

            company = (
                company_elem.inner_text().strip()
                if company_elem
                else "Unknown"
            )
            location = (
                location_elem.inner_text().strip()
                if location_elem
                else "Unknown"
            )

            location = location.replace("Bengaluru", "Bangalore")

            link_elem = job.query_selector("a")
            raw_link = link_elem.get_attribute("href") if link_elem else None

            if raw_link and "/jobs/view/" in raw_link:
                job_id = raw_link.split("/jobs/view/")[1].split("/")[0]
                link = f"https://www.linkedin.com/jobs/view/{job_id}/"
            else:
                link = raw_link

            job_data = {
                "title": title,
                "company": company,
                "location": location,
                "link": link,
                "source": "linkedin",
                "time_posted": time_posted,
                "applied": applied,
                "hiring_manager": hiring_manager,
                "score": 0,
            }

            title_lower = title.lower()
            loc_lower = location.lower()

            excluded_keywords = [
                "intern",
                "analyst",
                "consultant",
                "designer",
                "principal",
                "staff",
                "director",
                "head",
                "chief",
                "vp",
                "vice president",
            ]

            if any(x in title_lower for x in excluded_keywords):
                continue

            v2k, _v2_src = generate_job_key_v2(job_data)
            if v2k in seen_job_key_v2:
                if metrics is not None:
                    metrics.duplicate_cards_skipped += 1
                _li_diag_log(
                    f"card_index={idx} pass={dom_pass_label!r} "
                    f"skip_duplicate_JOB_KEY_V2 v2={v2k!r}"
                , verbose=True)
                continue
            seen_job_key_v2.add(v2k)
            jobs.append(job_data)
            appended_this_pass += 1

        except Exception as e:
            _li_diag_log(
                f"card_index={idx} pass={dom_pass_label!r} card_iteration_exception: {e!r}\n"
                f"{traceback.format_exc()}"
            , verbose=True)
            continue

    _li_diag_log(
        f"linkedin_list_dom_pass_done label={dom_pass_label!r} "
        f"list_rows={len(job_cards)} appended_this_pass={appended_this_pass} "
        f"jobs_total={len(jobs)} v2_unique={len(seen_job_key_v2)} "
        f"main_frame_nav_events={nav_state.get('nav_events')}",
        verbose=True,
    )



def save_linkedin_session():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()

        page = context.new_page()
        page.goto("https://www.linkedin.com/login")

        print("👉 Login manually, then press ENTER here")
        input()

        context.storage_state(path=str(paths.linkedin_auth_json()))
        browser.close()


def scrape_linkedin_jobs(search_url, query_run=None):
    """
    Scrape one LinkedIn search URL. Optional ``query_run`` dict (query_id, query_group,
    label, filter_profile) is attached to each returned job for orchestration metadata.
    """
    jobs = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(storage_state=str(paths.linkedin_auth_json()))

        trace_on = os.environ.get("LINKEDIN_PLAYWRIGHT_TRACE", "").lower() in (
            "1",
            "true",
            "yes",
        )
        trace_path = os.environ.get(
            "LINKEDIN_PLAYWRIGHT_TRACE_PATH", "linkedin_playwright_trace.zip"
        ).strip()
        if trace_on:
            context.tracing.start(screenshots=True, snapshots=True)
            _li_diag_log(f"playwright_tracing_started path={trace_path!r}", verbose=True)

        page = context.new_page()

        nav_state = {"last_url": None, "nav_events": 0}

        def on_frame_navigated(frame):
            if frame != page.main_frame:
                return
            u = page.url
            nav_state["nav_events"] = nav_state.get("nav_events", 0) + 1
            prev = nav_state["last_url"]
            if prev is None:
                nav_state["last_url"] = u
                _li_diag_log(f"MAIN_NAV initial url={u[:240]}", verbose=True)
                return
            if prev != u:
                _li_diag_log(
                    f"MAIN_NAV url_change nav_event={nav_state['nav_events']} "
                    f"prev={prev[:200]!r} -> new={u[:240]!r}"
                , verbose=True)
                nav_state["last_url"] = u

        page.on("framenavigated", on_frame_navigated)

        rf_state = {"n": 0}

        def on_request_failed(request):
            if rf_state["n"] >= 30:
                return
            url = request.url or ""
            if "linkedin.com" not in url.lower():
                return
            try:
                fail = request.failure
                ftxt = fail if isinstance(fail, str) else repr(fail)
            except Exception:
                ftxt = "?"
            rf_state["n"] += 1
            _li_diag_log(
                f"requestfailed[{rf_state['n']}] {url[:160]} failure={ftxt[:120]}"
            , verbose=True)

        page.on("requestfailed", on_request_failed)

        try:
            if debug_linkedin_enabled():
                print("\nOpening LinkedIn jobs page...")

            nav_spec = (query_run or {}).get("qualification_navigation")
            if nav_spec:
                _li_navigate_to_qualification_landing(
                    page,
                    entry_url=nav_spec.get("entry_url"),
                    keywords=str(nav_spec.get("keywords", "") or ""),
                    geo_id=str(nav_spec.get("geo_id", "") or ""),
                )
            else:
                page.goto(search_url)

            on_qual_landing = bool(
                nav_spec or _li_is_qualification_landing_url(page.url)
            )
            initial_wait_ms = 2500 if nav_spec else 8000
            if initial_wait_ms > 0:
                _li_human_pause(page, initial_wait_ms, initial_wait_ms + 800)
            _li_diag_log(f"post_initial_wait url={page.url[:240]}", verbose=True)

            skip_jobs_tab = on_qual_landing
            if skip_jobs_tab:
                _li_diag_log(
                    "Jobs tab click skipped: qualification_landing_url",
                    verbose=True,
                )
                try:
                    _li_job_card_locator(page).first.wait_for(
                        state="visible", timeout=12000
                    )
                    _li_diag_log(
                        f"qualification_cards_detected count={_li_count_job_cards(page)}",
                        verbose=True,
                    )
                except Exception as e:
                    _li_diag_log(f"qualification_cards_wait_failed: {e!r}", verbose=True)
            else:
                # click "Jobs" tab if needed (LinkedIn sometimes loads blank first)
                try:
                    page.click("button[aria-label='Jobs']", timeout=5000)
                    _li_diag_log("Jobs tab click attempted (ok)", verbose=True)
                except Exception as e:
                    _li_diag_log(f"Jobs tab click skipped: {e!r}", verbose=True)

            if skip_jobs_tab:
                _li_human_pause(page, 1500, 3000)
            else:
                page.wait_for_timeout(5000)
            _li_diag_log(
                f"post_tab_wait cards={_li_count_job_cards(page)} url={page.url[:240]}"
            , verbose=True)

            jobs_root, jobs_root_desc = _li_get_jobs_expansion_root(page)
            if jobs_root is not None:
                _li_diag_log(
                    f"qualification_jobs_root_selected desc={jobs_root_desc!r}"
                    if on_qual_landing
                    else f"jobs_expansion_root desc={jobs_root_desc!r}",
                    verbose=True,
                )
            scroll_loc, scroll_loc_desc = _li_find_inner_jobs_scroll_locator(page)
            if scroll_loc is not None:
                _li_diag_log(
                    f"using_inner_scroll_container selector={scroll_loc_desc!r}"
                , verbose=True)
            else:
                _li_diag_log(
                    f"using_inner_scroll_container selector={scroll_loc_desc!r} "
                    "(page.mouse.wheel fallback)"
                , verbose=True)

            n_before_scroll_phase = _li_count_job_cards(page)
            probe_start = _li_scroll_probe(page)
            _li_diag_log(
                f"scroll_phase_start cards={n_before_scroll_phase} "
                f"url={page.url[:240]} probe_cardCount={probe_start.get('cardCount')} "
                f"scrollable_containers={len(probe_start.get('containers') or [])}"
            , verbose=True)

            processed_job_ids: set[str] = set()
            seen_job_key_v2: set[str] = set()
            trav_metrics = _LinkedInTraversalMetrics()
            trav_ctx = _LinkedInTraversalContext()

            summ = _li_adaptive_scroll_traversal(
                page,
                scroll_loc,
                scroll_loc_desc,
                metrics=trav_metrics,
                trav_ctx=trav_ctx,
            )
            trav_ctx.note_page_state(page)
            _li_scrape_visible_job_cards_into(
                page,
                jobs,
                processed_job_ids,
                seen_job_key_v2,
                "after_initial_adaptive",
                nav_state,
                metrics=trav_metrics,
            )
            trav_metrics.pages_visited = 1
            trav_metrics.jobs_accumulated = len(jobs)
            trav_metrics.unique_v2_jobs = len(seen_job_key_v2)

            summ = _li_orchestrate_expansion_then_resume_traversal(
                page,
                scroll_loc,
                scroll_loc_desc,
                summ,
                on_post_pagination_dom_settled=lambda pg, lbl: _li_scrape_visible_job_cards_into(
                    pg,
                    jobs,
                    processed_job_ids,
                    seen_job_key_v2,
                    lbl,
                    nav_state,
                    metrics=trav_metrics,
                ),
                metrics=trav_metrics,
                trav_ctx=trav_ctx,
            )


            pag = _li_pagination_probe(page)
            _li_diag_log(f"pagination_probe_counts (presence only, no clicks)={pag}", verbose=True)

            _li_clear_scroll_harness(page)
            _li_clear_expansion_root_harness(page)

            n_after_scroll_phase = _li_count_job_cards(page)
            _li_diag_log(
                f"scroll_phase_end cards_before_phase={n_before_scroll_phase} "
                f"cards_after_phase={n_after_scroll_phase}"
            )

            trav_metrics.jobs_accumulated = len(jobs)
            trav_metrics.unique_v2_jobs = len(seen_job_key_v2)
            _li_diag_log(
                f"linkedin_multipage_accumulation_done jobs_total={len(jobs)} "
                f"v2_unique={len(seen_job_key_v2)} "
                f"main_frame_nav_events={nav_state.get('nav_events')}"
            )
            trav_metrics.print_summary()
            if debug_linkedin_enabled():
                print(f"Found {len(jobs)} job cards")

            if query_run:
                ts = query_run.get("run_ts")
                for job in jobs:
                    job["linkedin_query_id"] = query_run.get("query_id")
                    job["linkedin_query_group"] = query_run.get("query_group")
                    job["linkedin_query_label"] = query_run.get("label")
                    job["linkedin_filter_profile"] = query_run.get("filter_profile")
                    if ts:
                        job["linkedin_run_ts"] = ts

        finally:
            if trace_on:
                context.tracing.stop(path=trace_path)
                _li_diag_log(f"playwright_tracing_stopped path={trace_path!r}", verbose=True)
            browser.close()

        return jobs


# =========================
# LOGIN SESSION SETUP (RUN ONCE)
# =========================
def save_login_session():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()

        page.goto("https://www.linkedin.com/login")

        print("🔐 Log in manually, then press ENTER here...")
        input()

        context.storage_state(path=str(paths.linkedin_auth_json()))
        print("✅ Session saved!")

        browser.close()


if __name__ == "__main__":
    save_linkedin_session()
