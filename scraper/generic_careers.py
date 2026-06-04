"""
Generic Careers Scraper (Playwright)

Purpose:
- Scrape company career pages that do NOT use standard ATS (Lever/Greenhouse)
- Works across multiple Indian startup career pages
- No company-specific hacks (scalable approach)

Approach:
- Load page using Playwright
- Extract visible text elements
- Filter for relevant product/AI roles
"""

from playwright.sync_api import sync_playwright
from scraper.weworkremotely import score_job


def scrape_generic_careers():
    jobs = []

    print("\nOpening Generic Career Pages...\n")

    # ✅ ONLY put companies here that are NOT on Lever/Greenhouse
    CAREER_URLS = [
        "https://razorpay.com/jobs",
        "https://careers.phonepe.com",
        "https://olacareers.turbohire.co",
        # Add more here gradually
    ]

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        for url in CAREER_URLS:
            print(f"Opening {url}...")

            page = browser.new_page()

            try:
                page.goto(url, timeout=10000)
                page.wait_for_timeout(3000)
            except Exception as e:
                print(f"Skipping {url} (failed to load)")
                continue

                # Extract all visible text elements
                elements = page.query_selector_all("a, div, span")

                for el in elements:
                    try:
                        text = el.inner_text().strip()
                    except:
                        continue

                    if not text:
                        continue

                    title_lower = text.lower()

                    # ==============================
                    # 🎯 FILTER FOR RELEVANT ROLES
                    # ==============================
                    if not any(keyword in title_lower for keyword in [
                        "product manager",
                        "product owner",
                        "ai",
                        "machine learning",
                        "ml"
                    ]):
                        continue

                    # ❌ Remove unwanted roles
                    if any(bad in title_lower for bad in [
                        "intern",
                        "growth",
                        "category",
                        "sales",
                        "marketing"
                    ]):
                        continue

                    score = score_job(text)

                    if score < 3:
                        continue

                    jobs.append({
                        "title": text,
                        "company": url.split("//")[1].split(".")[0],
                        "location": "India / APAC",
                        "time_posted": "N/A",
                        "score": score,
                        "link": url
                    })

            except Exception as e:
                print(f"Error scraping {url}: {e}")

        browser.close()

    print(f"\nTotal Generic jobs collected: {len(jobs)}\n")

    return jobs