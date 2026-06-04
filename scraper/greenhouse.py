import requests
from scraper.company_sources import COMPANY_DATA

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
# ==============================
# LOCATION FILTER
# ==============================
def is_valid_location(location):

    location = location.lower()

    # Allow remote
    if "remote" in location:
        return True

    # Allow India
    if "india" in location:
        return True

    return False


# ==============================
# GREENHOUSE SCRAPER
# ==============================
def scrape_greenhouse_jobs():
    jobs = []

    COMPANY_BOARDS = COMPANY_DATA["greenhouse"]

    print("\nOpening Greenhouse...\n")

    for company in COMPANY_BOARDS:
        try:
            url = f"https://boards-api.greenhouse.io/v1/boards/{company}/jobs"
            response = requests.get(url)

            if response.status_code != 200:
                continue

            data = response.json()

            print(f"{company}: {len(data['jobs'])} jobs found")

            for job in data.get("jobs", []):

                # 🛑 Skip broken entries
                if not isinstance(job, dict):
                    continue
                
                title = job.get("title", "").strip()
                location = job.get("location", {}).get("name", "Remote")
                link = job.get("absolute_url")

                # ==============================
                # LOCATION FILTER (HERE)
                # ==============================
                loc = location.lower()

                # ❌ Reject clearly US / Europe locked roles
                if any(x in loc for x in ["united states", "usa", "san francisco", "new york", "nyc"]):
                    continue

                if any(x in loc for x in ["uk", "europe", "london", "berlin"]):
                    continue

                # ✅ Allow India + APAC + true global
                allowed_keywords = [
                    "india", "bangalore", "bengaluru", "mumbai",
                    "singapore", "indonesia", "malaysia", "philippines",
                    "apac", "asia", "remote", "anywhere", "global"
                ]

                if not any(word in loc for word in allowed_keywords):
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
                    "source": "greenhouse"
                })

        except Exception as e:
            print(f"Error with {company}: {e}")
            continue

    print(f"\n📦 GREENHOUSE RAW JOBS COLLECTED: {len(jobs)}")
    return jobs