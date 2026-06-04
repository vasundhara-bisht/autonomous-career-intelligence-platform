# =========================================================
# 🧼 JOB NORMALIZATION LAYER
# =========================================================
# Purpose:
# - Standardize job fields across all scrapers
# - Clean inconsistent formatting
# - Improve deduplication stability
# - Improve AI consistency
#
# IMPORTANT:
# - Runs BEFORE Stage 1 filtering
# - Does NOT perform scoring or rejection
# =========================================================

def normalize_job(job):

    # =========================
    # 🧼 TITLE CLEANUP
    # =========================
    title = str(job.get("title", "")).strip()

    # Normalize whitespace
    title = " ".join(title.split())

    # Normalize seniority aliases
    title = title.replace("Sr.", "Senior")
    title = title.replace("Sr ", "Senior ")
    title = title.replace("Jr.", "Junior")
    title = title.replace("Jr ", "Junior ")

    # Normalize PM aliases
    title = title.replace("PM II", "Product Manager II")
    title = title.replace("PM 2", "Product Manager II")
    title = title.replace("PM III", "Product Manager III")
    title = title.replace("PM 3", "Product Manager III")

    # =========================
    # 🧼 COMPANY CLEANUP
    # =========================
    company = str(job.get("company", "")).strip()

    company = " ".join(company.split())

    # =========================
    # 📍 LOCATION CLEANUP
    # =========================
    location = str(job.get("location", "Unknown")).strip()

    location = location.replace("Bengaluru", "Bangalore")

    # =========================
    # 🔗 LINK CLEANUP
    # =========================
    link = str(job.get("link", "")).strip()

    # =========================
    # ⏱ TIME CLEANUP
    # =========================
    time_posted = str(job.get("time_posted", "Unknown")).strip()

    # =========================
    # 🌐 SOURCE CLEANUP
    # =========================
    source = str(job.get("source", "unknown")).strip().lower()

    # =========================
    # 🧠 HELPER FIELDS (DEDUP SUPPORT)
    # =========================
    normalized_title = " ".join(title.lower().split())
    normalized_company = " ".join(company.lower().split())

    # =========================
    # ✅ RETURN NORMALIZED JOB
    # =========================

    # Preserve original fields
    normalized_job = job.copy()

    # Overwrite cleaned core fields
    normalized_job.update({
        "title": title,
        "company": company,
        "location": location,
        "time_posted": time_posted,
        "link": link,
        "source": source,

        # Helper fields
        "normalized_title": normalized_title,
        "normalized_company": normalized_company
    })

    return normalized_job