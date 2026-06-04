from playwright.sync_api import sync_playwright


def fetch_job_description(job):
    link = job.get("link")

    if not link:
        job["description"] = ""
        return job

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()

            page.goto(link, timeout=45000, wait_until="domcontentloaded")
            page.wait_for_timeout(1500)

            # ✅ LinkedIn descriptions render asynchronously
            if job.get("source") == "linkedin":
                try:
                    page.wait_for_selector(
                        "div.jobs-description, section.show-more-less-html",
                        timeout=5000,
                    )
                except:
                    pass

            # ==============================
            # 🎯 SMART DESCRIPTION TARGETING
            # ==============================

            # ✅ LinkedIn-specific selectors
            if job.get("source") == "linkedin":

                selectors = [
                    "div.jobs-description",
                    "div.jobs-box__html-content",
                    "div.jobs-description-content__text",
                    "div.jobs-description__content",
                    "section.show-more-less-html",
                ]

            # ✅ Generic selectors (other scrapers)
            else:

                selectors = [
                    "div.description",
                    "div.job-description",
                    "div.content",
                    "section",
                    "main",
                    "article",
                    "div.listing-container",
                ]

            description = ""

            for selector in selectors:
                try:
                    elements = page.query_selector_all(selector)

                    combined_text = " ".join(
                        [
                            el.inner_text().strip()
                            for el in elements
                            if el.inner_text().strip()
                        ]
                    )

                    # ✅ Use first meaningful content
                    if len(combined_text) > 500:
                        description = combined_text
                        break

                except:
                    continue

            browser.close()

    except Exception as e:
        print(f"❌ Description fetch failed: {e}")
        description = ""

    job["description"] = description
    return job
