import re

# ==========================================================
# 🎯 ROLE SCORING ENGINE
# ==========================================================
def score_job(title: str) -> int:
    if not title:
        return 0

    title = title.lower()

    # =========================
    # ❌ HARD EXCLUSION
    # =========================
    EXCLUDE = [
        "product marketing",
        "product designer",
        "product analyst",
        "support",
        "customer",
        "intern",
        "staff",
        "principal",
        "director",
        "vp",
        "head",
        "group"
    ]

    if any(re.search(rf"\b{re.escape(k)}\b", title) for k in EXCLUDE):
        return 0

    # PM / PO / lead positives live in STRONG and other signals below (no hard title gate).

    score = 0

    # 🎮 GAMING BOOST (force-pass Stage 1)
    gaming_keywords = ["game", "gaming", "games", "esports"]

    text = title.lower()

    if any(k in text for k in gaming_keywords):
        score += 6

    # =========================
    # 🎯 STRONG SIGNALS
    # =========================
    STRONG = {
        "product manager": 6,
        "product owner": 6
    }

    for k, v in STRONG.items():
        if k in title:
            score += v

    # =========================
    # ⚡ BASE SIGNAL
    # =========================
    if "product" in title:
        score += 2

    # =========================
    # 💎 BONUS SIGNALS
    # =========================
    BONUS = ["senior", "lead", "growth"]

    for k in BONUS:
        if k in title:
            score += 2

    # =========================
    # 🚀 DOMAIN BOOSTS
    # =========================
    DOMAIN = ["ai", "ml", "platform", "saas", "fintech"]

    for k in DOMAIN:
        if k in title:
            score += 1

    # =========================
    # ❌ NEGATIVE SIGNALS
    # =========================
    NEGATIVE = {
        "engineer": -6,
        "developer": -6,
        "data scientist": -7,
        "scientist": -6,
        "analyst": -5,
        "data": -4,
        "marketing": -2,
        "sales": -3,
        "technical": -3
    }

    for k, v in NEGATIVE.items():
        if k in title:
            score += v

    return score


# ==========================================================
# 📍 LOCATION FILTER (STANDARDIZED)
# ==========================================================
def is_valid_location(location: str) -> bool:
    if not location:
        return False

    loc = location.lower()

    # ❌ Reject US / Europe locked roles
    if any(x in loc for x in ["united states", "usa", "new york", "san francisco"]):
        return False

    if any(x in loc for x in ["uk", "europe", "london", "berlin"]):
        return False

    # ✅ Allow India + APAC + global remote
    allowed_keywords = [
        "india", "bangalore", "bengaluru", "mumbai",
        "delhi", "hyderabad", "pune", "chennai",
        "apac", "asia", "remote", "anywhere", "global"
    ]

    return any(word in loc for word in allowed_keywords)


# ==========================================================
# 🧠 STAGE 1 FILTER (CORE ENGINE)
# ==========================================================
def apply_stage1_filter(job: dict) -> dict | None:
    """
    Returns:
        job (updated) if accepted
        None if rejected
    """

    title = job.get("title", "")
    location = job.get("location", "")

    # =========================
    # 🎯 SCORE JOB
    # =========================
    score = score_job(title)

    # ❌ Reject low score
    if score < 4:
        job["score"] = score
        job["rejected"] = True 
        return job               

    # =========================
    # 📍 LOCATION FILTER
    # =========================
    if not is_valid_location(location):
        job["score"] = score
        
        # 🔧 FIX: Only reject if ALSO low score
        if score < 7:
            job["rejected"] = True
        
        return job

    # =========================
    # ✅ ACCEPT
    # =========================
    job["score"] = score

    # 🔧 CRITICAL FIX: ensure accepted jobs are NOT marked rejected
    job["rejected"] = False

    return job