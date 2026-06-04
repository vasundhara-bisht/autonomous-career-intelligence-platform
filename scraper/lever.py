import requests
from scraper.company_sources import COMPANY_DATA


def scrape_lever_jobs():
    jobs = []

    session = requests.Session()

    print("\nOpening Lever...")

    COMPANY_HANDLES = COMPANY_DATA["lever"]

    for company in COMPANY_HANDLES:
        try:
            url = f"https://api.lever.co/v0/postings/{company}?mode=json"
            response = session.get(url, timeout=5)

            if response.status_code != 200:
                print(f"{company}: ❌ Failed ({response.status_code})")
                continue

            data = response.json()

            if not data:
                print(f"{company}: ⚠️ No jobs (likely not using Lever)")
                continue

            print(f"{company}: {len(data)} jobs found")

            for job in data:
                title = job.get("text", "").strip()
                location = job.get("categories", {}).get("location", "Remote")
                link = job.get("hostedUrl")

                if not title or not link:
                    continue


                # =====================================
                # LIGHTWEIGHT PRE-FILTER (SCRAPER LEVEL)
                # =====================================
                # Purpose:
                # - Cheap early rejection
                # - Reduce irrelevant jobs before pipeline
                # - Avoid unnecessary AI/token costs
                #
                # NOTE:
                # Final Stage 1 scoring still happens via
                # apply_stage1_filter().
                # =====================================

                # =========================
                # 📍 LOCATION FILTER
                # =========================
                loc = location.lower()

                # ❌ Reject region-locked remote
                if "united states" in loc or "usa" in loc:
                    continue

                if "uk" in loc or "europe" in loc:
                    continue

                # ✅ India cities detection (CRITICAL FIX)
                india_keywords = [
                    "india", "bangalore", "bengaluru", "mumbai",
                    "delhi", "gurgaon", "hyderabad", "pune",
                    "chennai", "noida"
                ]

                if not any(word in loc for word in india_keywords) and \
                   not ("remote" in loc or "anywhere" in loc):
                        continue

                if company:
                    company = company.strip()
                    if company.lower() in ["new", "featured", "hot"]:
                        company = "Unknown"

                jobs.append({
                    "title": title,
                    "company": company.capitalize(),
                    "location": location,
                    "time_posted": "Unknown",
                    "link": link,
                    "source": "lever"
                })

        except Exception as e:
            print(f"Error with {company}: {e}")
            continue

    print(f"\n📦 LEVER RAW JOBS COLLECTED: {len(jobs)}")
    return jobs