from rapidfuzz import fuzz


def _job_key_v2_for_dedup(job: dict) -> str:
    """Non-empty JOB_KEY_V2 string, or empty if missing/blank."""
    v = job.get("JOB_KEY_V2")
    if v is None:
        return ""
    return str(v).strip()


# =========================
# 🧠 HELPER: EXTRACT SENIORITY
# =========================
def extract_seniority(title):
    """
    Categorizes job seniority to prevent incorrect deduplication.
    """

    title = str(title).lower()

    if any(x in title for x in ["intern"]):
        return "intern"

    if any(x in title for x in ["junior", "associate", "jr"]):
        return "junior"

    if any(x in title for x in ["senior", "sr"]):
        return "senior"

    # 🔧 FIX: Split seniority levels properly (previously everything was grouped)
    if "lead" in title:
        return "lead"

    if any(x in title for x in ["principal", "staff"]):
        return "principal"

    if any(x in title for x in ["director", "vp", "head"]):
        return "exec"

    return "mid"


def deduplicate_jobs(jobs, observability: dict | None = None):
    """
    Deduplicates jobs globally across all sources.

    Logic:
    0. JOB_KEY_V2 match (Phase 3)
    → If both jobs have the same non-empty JOB_KEY_V2, treat as duplicate
      (before link/fuzzy checks).

    1. Exact Match (link)
    → If URLs are identical, treat as duplicate

    2. Fuzzy Match (title + company)
    → Uses similarity scoring:
        - VERY strict threshold
        - Only if seniority matches

    observability: optional dict; records v2/exact/fuzzy dedup hit counts when provided.

    Why after filtering?
    → Reduces computation

    Why before description fetch?
    → Avoid unnecessary browser calls
    """

    print("Checking V2 identity matches...")
    print("Checking exact URL matches...")
    print("Checking fuzzy matches...")

    unique_jobs = []
    v2_dedup_hits = 0
    exact_dedup_hits = 0
    fuzzy_dedup_hits = 0

    for job in jobs:
        is_duplicate = False

        for seen in unique_jobs:

            # =========================
            # 🆔 JOB_KEY_V2 MATCH (early, before link + fuzzy)
            # =========================
            job_v2 = _job_key_v2_for_dedup(job)
            seen_v2 = _job_key_v2_for_dedup(seen)
            if job_v2 and seen_v2 and job_v2 == seen_v2:
                print("\n" + "=" * 30)
                print("🆔 DUPLICATE DETECTED (V2)")
                print("=" * 30)
                print(
                    f"❌ Removed [{job.get('source', 'unknown').upper()}]: "
                    f"{job.get('title')} @ {job.get('company')}"
                )
                print(
                    f"↳ Existing [{seen.get('source', 'unknown').upper()}]: "
                    f"{seen.get('title')} @ {seen.get('company')}"
                )
                print("🧠 JOB_KEY_V2 MATCH:")
                print(job_v2)
                print("=" * 30)

                v2_dedup_hits += 1
                is_duplicate = True
                break

            # =========================
            # 🔗 EXACT MATCH (LINK)
            # =========================
            if job["link"] == seen["link"]:

                # 🔧 CRITICAL FIX: ensure titles are ALSO same
                job_title = str(job.get("title", "")).lower().strip()
                seen_title = str(seen.get("title", "")).lower().strip()

                if job_title != seen_title:
                    continue

                print("\n" + "=" * 60)
                print("🔁 DUPLICATE DETECTED (EXACT)")
                print(
                    f"❌ Removed [{job.get('source', 'unknown').upper()}]: "
                    f"{job.get('title')} @ {job.get('company')}"
                )
                print(
                    f"↳ Existing [{seen.get('source', 'unknown').upper()}]: "
                    f"{seen.get('title')} @ {seen.get('company')}"
                )
                print("=" * 60)

                exact_dedup_hits += 1
                is_duplicate = True
                break

            # =========================
            # 🧠 FUZZY MATCH (title + company)
            # =========================
            title_score = fuzz.ratio(
                str(job.get("title", "")).lower(),
                str(seen.get("title", "")).lower()
            )

            company_score = fuzz.ratio(
                str(job.get("company", "")).lower(),
                str(seen.get("company", "")).lower()
            )

            # =========================
            # ✅ STRICT FUZZY DEDUP (MORE SAFE NOW)
            # =========================
            # 🔧 FINAL STRICT DEDUP RULE

            # 🔧 CRITICAL FIX: don't dedupe different roles at same company
            job_title = str(job.get("title", "")).lower()
            seen_title = str(seen.get("title", "")).lower()

            role_keywords = ["senior", "lead", "junior", "associate"]

            job_roles = [k for k in role_keywords if k in job_title]
            seen_roles = [k for k in role_keywords if k in seen_title]

            # Only dedupe if roles match OR both have no role keyword
            same_role = job_roles == seen_roles

            if same_role and title_score >= 98 and company_score >= 98:
                print("\n" + "=" * 60)
                print("🧠 DUPLICATE DETECTED (FUZZY)")
                print(
                    f"❌ Removed [{job.get('source', 'unknown').upper()}]: "
                    f"{job.get('title')} @ {job.get('company')}"
                )

                print(
                    f"↳ Existing [{seen.get('source', 'unknown').upper()}]: "
                    f"{seen.get('title')} @ {seen.get('company')}"
                )

                print(f"📊 Title match: {title_score}%")
                print(f"📊 Company match: {company_score}%")
                print("=" * 60)

                fuzzy_dedup_hits += 1
                is_duplicate = True
                break

        if not is_duplicate:
            unique_jobs.append(job)

    if v2_dedup_hits == 0 and exact_dedup_hits == 0 and fuzzy_dedup_hits == 0:
        print(
            "No duplicates found across V2, exact URL, or fuzzy matching."
        )

    line = "=" * 60
    print(line)
    print("📊 DEDUP SUMMARY")
    print(f"v2_dedup_hits: {v2_dedup_hits}")
    print(f"exact_dedup_hits: {exact_dedup_hits}")
    print(f"fuzzy_dedup_hits: {fuzzy_dedup_hits}")
    if observability is not None:
        observability["v2_dedup_hits"] = v2_dedup_hits
        observability["exact_dedup_hits"] = exact_dedup_hits
        observability["fuzzy_dedup_hits"] = fuzzy_dedup_hits
    print(line)

    return unique_jobs