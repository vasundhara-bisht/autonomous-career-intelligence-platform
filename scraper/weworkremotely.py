from playwright.sync_api import sync_playwright
import re
from difflib import SequenceMatcher
from urllib.parse import urljoin, urlparse

from agent.filter_engine import score_job

_WWR_ORIGIN = "https://weworkremotely.com"


def _pick_wwr_listing_href(job) -> str | None:
    """
    Prefer /remote-jobs/ listing URLs; skip sponsor listing_ads links.
    Deterministic: among /remote-jobs/ candidates, longest path wins.
    """
    anchors = job.query_selector_all("a[href]")
    remote_jobs_hrefs: list[str] = []

    for a in anchors:
        href = (a.get_attribute("href") or "").strip()
        if not href:
            continue
        low = href.lower()
        if "listing_ads" in low:
            continue
        abs_url = urljoin(_WWR_ORIGIN + "/", href)
        path = urlparse(abs_url).path.lower()
        if "/remote-jobs/" in path:
            remote_jobs_hrefs.append(href)

    if remote_jobs_hrefs:

        def path_len(h: str) -> int:
            return len(urlparse(urljoin(_WWR_ORIGIN + "/", h)).path)

        return max(remote_jobs_hrefs, key=path_len)

    title_link = job.query_selector("span.title a[href]")
    if title_link:
        th = (title_link.get_attribute("href") or "").strip()
        if th and "listing_ads" not in th.lower():
            return th

    for a in anchors:
        href = (a.get_attribute("href") or "").strip()
        if not href:
            continue
        if "listing_ads" in href.lower():
            continue
        return href

    return None


# ==========================================================
# MAIN SCRAPER FUNCTION
# ==========================================================

def scrape_weworkremotely_jobs():
    jobs = []  # This will store final job data

    with sync_playwright() as p:

        # Launch browser
        browser = p.chromium.launch(headless=False, slow_mo=800)
        page = browser.new_page()

        print("Opening WeWorkRemotely...")

        # Open jobs page
        page.goto(
            "https://weworkremotely.com/categories/remote-product-jobs",
            timeout=45000,
            wait_until="domcontentloaded"
        )

        # Wait for content to load
        page.wait_for_timeout(8000)

        # ==========================================================
        # STEP 1: FIND JOB SECTIONS
        # ==========================================================
        sections = page.query_selector_all("section.jobs")
        print(f"Found {len(sections)} sections")

        # ==========================================================
        # STEP 2: LOOP THROUGH EACH SECTION
        # ==========================================================
        for section in sections:

            job_cards = section.query_selector_all("li")

            print(f"Found {len(job_cards)} potential job cards in section")

            # ==========================================================
            # STEP 3: LOOP THROUGH JOB CARDS
            # ==========================================================
            for job in job_cards:

                try:
                    # ==========================================================
                    # EXTRACT TITLE & COMPANY (PRIMARY SELECTORS)
                    # ==========================================================
                    title = None
                    company = None
                    time_posted = None

                    # Try structured selectors first
                    title_element = job.query_selector("span.title")
                    company_element = job.query_selector("span.company")

                    if title_element:
                        title = title_element.inner_text().strip()

                        # 🔧 FIX: skip wrong titles (company showing as title)
                        if company and title and title.lower() == company.lower():
                            title = None

                    if company_element:
                        company = company_element.inner_text().strip()
                    
                    # 🔧 SKIP INVALID JOBS (bad WWR data)
                    if title and company and title.lower() == company.lower():
                        continue

                    # ==========================================================
                    # FALLBACK: SMART TEXT PARSING (VERY IMPORTANT)
                    # ==========================================================

                    if not title or not company:

                        full_text = job.inner_text().strip().split("\n")

                        cleaned_lines = []
                        time_posted = None  # NEW FIELD

                        for line in full_text:
                            line_clean = line.strip().lower()

                            # Capture time like "4d"
                            if line_clean.endswith("d") and line_clean[:-1].isdigit():
                                time_posted = line.strip()
                                continue

                            # Skip noise
                            if (
                                not line_clean
                                or "ago" in line_clean
                                or "full-time" in line_clean
                                or "contract" in line_clean
                                or "anywhere" in line_clean
                                or "remote" in line_clean
                            ):
                                continue

                            # ✅ THIS MUST BE INSIDE LOOP
                            cleaned_lines.append(line.strip())


                        # AFTER LOOP (not inside)
                        if len(cleaned_lines) >= 2:
                            title = cleaned_lines[0]
                            company = cleaned_lines[1]   


                    # =========================
                    # ⏱ ENSURE TIME IS ALWAYS CAPTURED
                    # =========================
                    if not time_posted:
                        full_text = job.inner_text().strip().split("\n")

                        for line in full_text:
                            line_clean = line.strip().lower()

                            if line_clean.endswith("d") and line_clean[:-1].isdigit():
                                time_posted = line.strip()
                                break


                    # ==========================================================
                    # FINAL VALIDATION
                    # ==========================================================
                    if not title or not company:
                        #print("Skipping 🚫: Could not extract properly")
                        continue

                    # ==========================================================
                    # EXTRACT LINK — prefer /remote-jobs/ listing URL (not first <a>)
                    # ==========================================================

                    href = _pick_wwr_listing_href(job)

                    if not href:
                        continue

                    if href.startswith(("http://", "https://")):
                        link = href
                    else:
                        link = urljoin(_WWR_ORIGIN + "/", href)

                    # ==============================
                    # 🧠 SMART LOCATION EXTRACTION
                    # ==============================
                    full_text = job.inner_text().lower()
                    lines = [line.strip() for line in job.inner_text().split("\n") if line.strip()]

                    if "united states" in full_text or "usa" in full_text:
                        location = "Remote - US"
                    elif "europe" in full_text or "uk" in full_text:
                        location = "Remote - Europe"
                    elif "anywhere" in full_text or "worldwide" in full_text:
                        location = "Remote - Global"
                    elif "india" in full_text:
                        location = "India"
                    else:
                        location = "Remote"

                    loc = location.lower()

                    # =====================================
                    # LIGHTWEIGHT PRE-FILTER (SCRAPER LEVEL)
                    # =====================================
                    # Purpose:
                    # - Cheap early rejection
                    # - Reduce irrelevant jobs before pipeline
                    # - Avoid unnecessary downstream processing
                    #
                    # NOTE:
                    # Full Stage 1 filtering still happens later
                    # in the centralized pipeline.
                    # =====================================

                    # 🧠 Cheap title scoring
                    pre_score = score_job(title)

                    # ❌ Reject obvious garbage early
                    if pre_score < 3:
                        continue

                    # ==========================================================
                    # STORE RESULT
                    # ==========================================================

                    if company:
                        company = company.strip()
                        if company.lower() in ["new", "featured", "hot"]:
                            company = "Unknown"

                    
                    # 🔧 FIX: clean wrong title (company getting picked as title)
                    if title and company:
                        if title.lower() == company.lower():
                            continue  # skip bad extraction

                        if company.lower() in title.lower():
                            title = title.replace(company, "").strip(" -@")


                    jobs.append({
                        "title": title,
                        "company": company,
                        "location": location,
                        "time_posted": time_posted,
                        "link": link,
                        "source": "weworkremotely"
                    })

                except Exception as e:
                    print("Error:", e)
                    continue

        browser.close()

        print(f"\n📦 WWR RAW JOBS COLLECTED: {len(jobs)}")

    return jobs