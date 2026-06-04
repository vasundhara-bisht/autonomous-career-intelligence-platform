"""
JOB_KEY_V2 is the canonical job identity for dedup, final merge, historical lookup,
and (phased) description cache. Legacy JOB_KEY (normalized title::company) remains
a compatibility fallback during migration.

Generates deterministic JOB_KEY_V2 and identity_source tags per job.
"""

from __future__ import annotations

import hashlib
import os
import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from agent.historical_persistence import generate_job_key

# Identity-bearing query params: never strip (lowercase name match).
_PRESERVE_QUERY_KEYS = frozenset(
    {
        "gh_jid",
        "jobid",
        "job_id",
        "jk",
        "lever-via",
        "ashby_jid",
        "posting_id",
    }
)

# Tracking / marketing noise only (lowercase name match). Not exhaustive — unknown keys are kept.
_STRIP_QUERY_KEYS = frozenset(
    {
        "trk",
        "ref",
        "src",
        "original_referer",
        "mcid",
        "gh_src",
        "source",
        "campaign",
        "fbclid",
        "gclid",
        "li_fat_id",
        "lipi",
        "licu",
        "refid",
        "trackingid",
        "sessionid",
        "wd",
        "from",
        "recommended",
        "currentjobid",
        "eBP",
        "eBPNonJob",
    }
)

# Host aliases for deterministic canonical URL (lowercase host after www strip).
_HOST_ALIASES = {
    "m.linkedin.com": "linkedin.com",
    "mobile.linkedin.com": "linkedin.com",
    "job-boards.greenhouse.io": "boards.greenhouse.io",
    "www.job-boards.greenhouse.io": "boards.greenhouse.io",
}


def extract_linkedin_job_id(url: str | None) -> str | None:
    if not url or not isinstance(url, str):
        return None
    if "/jobs/view/" not in url:
        return None
    try:
        part = url.split("/jobs/view/", 1)[1].split("/")[0].split("?")[0].strip()
        if part.isdigit():
            return part
    except (IndexError, ValueError):
        pass
    return None


def extract_greenhouse_board_and_id(url: str | None) -> tuple[str | None, str | None]:
    """Parse board slug and numeric job id from Greenhouse absolute_url."""
    if not url or not isinstance(url, str):
        return None, None
    m = re.search(r"([^/]+)/jobs/(\d+)", url, re.IGNORECASE)
    if m:
        board, jid = m.group(1), m.group(2)
        if jid.isdigit():
            return board, jid
    return None, None


def extract_instahyre_job_id(url: str | None) -> str | None:
    """Parse numeric job id from Instahyre URLs (/job-418799-.../)."""
    if not url or not isinstance(url, str):
        return None
    m = re.search(r"/job-(\d+)(?:/|-)", url, re.IGNORECASE)
    if m and m.group(1).isdigit():
        return m.group(1)
    m = re.search(r"instahyre\.com/job-(\d+)", url, re.IGNORECASE)
    if m and m.group(1).isdigit():
        return m.group(1)
    return None


def extract_lever_handle_and_id(url: str | None) -> tuple[str | None, str | None]:
    """Parse company handle and posting id from Lever hostedUrl."""
    if not url or not isinstance(url, str):
        return None, None
    if "lever.co" not in url.lower():
        return None, None
    try:
        p = urlparse(url.strip())
        parts = [x for x in p.path.strip("/").split("/") if x]
        if len(parts) >= 2:
            return parts[0], parts[1]
    except (ValueError, IndexError):
        pass
    return None, None


def _normalize_host(netloc: str) -> str:
    host = netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    if ":" in host:
        name, _, port = host.partition(":")
        if port in ("443", "80") and name:
            host = name
    return _HOST_ALIASES.get(host, host)


def _normalize_path(path: str) -> str:
    if not path:
        return "/"
    if not path.startswith("/"):
        path = "/" + path
    while "//" in path:
        path = path.replace("//", "/")
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    if path.lower().endswith("/index.html"):
        path = path[: -len("/index.html")] or "/"
    return path or "/"


def normalize_canonical_url(url: str | None) -> str:
    if not url or not isinstance(url, str):
        return ""
    raw = url.strip()
    if not raw:
        return ""

    parsed = urlparse(raw)
    if not parsed.netloc:
        return ""

    scheme = (parsed.scheme or "https").lower()
    if scheme == "http":
        scheme = "https"

    netloc = _normalize_host(parsed.netloc)

    path = _normalize_path(parsed.path or "/")

    pairs: list[tuple[str, str]] = []
    for k, v in parse_qsl(parsed.query, keep_blank_values=True):
        lk = k.lower()
        if lk in _PRESERVE_QUERY_KEYS:
            pairs.append((lk, v))
        elif lk.startswith("utm_") or lk in _STRIP_QUERY_KEYS:
            continue
        else:
            pairs.append((lk, v))
    pairs.sort(key=lambda item: item[0])
    query = urlencode(pairs, doseq=True)

    clean = urlunparse((scheme, netloc, path, "", query, ""))
    return clean.strip()


def generate_job_key_v2(job: dict) -> tuple[str, str]:
    """
    Deterministic JOB_KEY_V2 and identity_source (Phase 0 tiers).

    Tier 1: source-specific id (LinkedIn, Greenhouse, Lever, Instahyre numeric job id)
    Tier 2: sha256(normalize_canonical_url(link)) -> v2:url:<hex>
    Tier 3: composite stable hash (link present but not used in tier 2, or extra entropy) -> v2:hash:<hex>
    Tier 4: legacy JOB_KEY fingerprint -> v2:legacy:<hex>

    Tier 3 vs 4: after tier 1–2 miss, use tier 3 when a non-empty link exists (malformed / non-canonical
    normalization); use tier 4 when link is empty so legacy JOB_KEY is the strongest stable signal.
    """
    source = str(job.get("source", "") or "").strip().lower()
    link = str(job.get("link", "") or "").strip()
    title = str(job.get("title", "") or "")
    company = str(job.get("company", "") or "")
    nt = str(job.get("normalized_title", "") or "").strip().lower()
    nc = str(job.get("normalized_company", "") or "").strip().lower()

    # ----- Tier 1 -----
    if source == "linkedin":
        lid = extract_linkedin_job_id(link)
        if lid:
            return f"v2:linkedin:{lid}", "linkedin_id"

    if source == "greenhouse":
        board, gid = extract_greenhouse_board_and_id(link)
        if gid:
            b = (board or "unknown").strip().lower()
            return f"v2:greenhouse:{b}:{gid}", "greenhouse_id"

    if source == "lever":
        handle, pid = extract_lever_handle_and_id(link)
        if handle and pid:
            h = handle.strip().lower()
            return f"v2:lever:{h}:{pid}", "lever_id"

    if source == "instahyre":
        iid = extract_instahyre_job_id(link)
        if iid:
            return f"v2:instahyre:{iid}", "instahyre_id"

    # ----- Tier 2 -----
    canon = normalize_canonical_url(link)
    if canon:
        digest = hashlib.sha256(canon.encode("utf-8")).hexdigest()
        return f"v2:url:{digest}", "canonical_url"

    legacy_key = str(job.get("JOB_KEY", "") or "").strip() or generate_job_key(job)
    payload = f"{source}|{link}|{title}|{company}|{nt}|{nc}"

    # ----- Tier 3 (composite hash) -----
    if link:
        h3 = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        return f"v2:hash:{h3}", "hash_fallback"

    # ----- Tier 4 (legacy JOB_KEY fingerprint) -----
    h4 = hashlib.sha256(legacy_key.encode("utf-8")).hexdigest()
    return f"v2:legacy:{h4}", "legacy_fallback"


# Phase 5 — collision classification (observability only; used by instrumentation)
SUSPICIOUS_HASH_GROUP_MIN = 3


def _canonical_link_for_collision(job: dict) -> str:
    link = str(job.get("link", "") or "").strip()
    if not link:
        return ""
    return (normalize_canonical_url(link) or "").strip()


def _is_expected_duplicate_collision_group(group: list[dict]) -> bool:
    """
    Healthy duplicate scrapes: same V2, same normalized link, company, title.
    """
    if len(group) < 2:
        return False
    v2k = str(group[0].get("JOB_KEY_V2", "") or "").strip()
    if not v2k or any(str(j.get("JOB_KEY_V2", "") or "").strip() != v2k for j in group):
        return False
    canons = [_canonical_link_for_collision(j) for j in group]
    if not all(canons) or len(set(canons)) != 1:
        return False
    companies = [
        str(j.get("normalized_company", "") or "").strip().lower() for j in group
    ]
    if len(set(companies)) != 1:
        return False
    titles = [str(j.get("normalized_title", "") or "").strip().lower() for j in group]
    if len(set(titles)) != 1:
        return False
    return True


def _suspicious_collision_rule_tags(group: list[dict]) -> list[str]:
    """Structural risk tags; empty if group should not count as suspicious."""
    if _is_expected_duplicate_collision_group(group):
        return []
    tags: list[str] = []
    canons = [_canonical_link_for_collision(j) for j in group]
    distinct_canon = {c for c in canons if c}
    if len(distinct_canon) >= 2:
        tags.append("S-URL")

    src0 = str(group[0].get("identity_source", "") or "")
    if src0 in ("linkedin_id", "greenhouse_id", "lever_id", "instahyre_id"):
        companies = [
            str(j.get("normalized_company", "") or "").strip().lower() for j in group
        ]
        if len(set(companies)) >= 2:
            tags.append("S-ID-CO")

    if src0 == "hash_fallback" and len(group) >= SUSPICIOUS_HASH_GROUP_MIN:
        tags.append("S-HASH-LARGE")

    return tags


def _collision_example_payload(v2k: str, group: list[dict]) -> dict:
    src0 = str(group[0].get("identity_source", "") or "")
    return {
        "job_key_v2": v2k,
        "identity_source": src0,
        "collision_size": len(group),
        "jobs": [
            {
                "source": str(j.get("source", "") or ""),
                "company": str(j.get("company", "") or ""),
                "title": str(j.get("title", "") or ""),
                "link": str(j.get("link", "") or ""),
            }
            for j in group
        ],
    }


_SOURCE_TO_METRIC = {
    "linkedin_id": "v2_from_linkedin_id",
    "greenhouse_id": "v2_from_greenhouse_id",
    "lever_id": "v2_from_lever_id",
    "instahyre_id": "v2_from_instahyre_id",
    "canonical_url": "v2_from_canonical_url",
    "hash_fallback": "v2_from_hash",
    "legacy_fallback": "v2_from_legacy",
}

# Tier-1 source-specific IDs = resolved; weaker tiers = unresolved (observability only).
_STRONG_IDENTITY_SOURCES = frozenset(
    {"linkedin_id", "greenhouse_id", "lever_id", "instahyre_id"}
)
_UNRESOLVED_SOURCE_BUCKETS = ("linkedin", "greenhouse", "lever", "instahyre", "other")


def instrument_jobs_identity_v2(jobs: list[dict]) -> dict:
    """
    Sets JOB_KEY_V2 and identity_source on each job dict; returns metrics for logging.
    """
    metrics: dict = {
        "v2_generated_count": 0,
        "v2_from_linkedin_id": 0,
        "v2_from_greenhouse_id": 0,
        "v2_from_lever_id": 0,
        "v2_from_instahyre_id": 0,
        "v2_from_canonical_url": 0,
        "v2_from_hash": 0,
        "v2_from_legacy": 0,
        "canonical_url_normalization_changed_count": 0,
        "samples": [],
    }

    for job in jobs:
        raw_link = str(job.get("link", "") or "").strip()
        if raw_link:
            canon_probe = normalize_canonical_url(raw_link)
            if canon_probe and canon_probe != raw_link:
                metrics["canonical_url_normalization_changed_count"] += 1
        v2, src = generate_job_key_v2(job)
        job["JOB_KEY_V2"] = v2
        job["identity_source"] = src
        metrics["v2_generated_count"] += 1
        mk = _SOURCE_TO_METRIC.get(src)
        if mk:
            metrics[mk] = metrics.get(mk, 0) + 1

    # Diverse samples: prefer one example per identity_source, then fill to 10
    seen_src: set[str] = set()
    seen_combo: set[tuple[str, str, str]] = set()
    samples: list[dict] = []
    for job in jobs:
        src = str(job.get("identity_source", ""))
        if src in seen_src:
            continue
        seen_src.add(src)
        leg = str(job.get("JOB_KEY", "") or "").strip() or generate_job_key(job)
        v2 = str(job.get("JOB_KEY_V2", ""))
        seen_combo.add((leg, v2, src))
        samples.append({"legacy": leg, "v2": v2, "source": src})
        if len(samples) >= 7:
            break
    for job in jobs:
        if len(samples) >= 10:
            break
        src = str(job.get("identity_source", ""))
        leg = str(job.get("JOB_KEY", "") or "").strip() or generate_job_key(job)
        v2 = str(job.get("JOB_KEY_V2", ""))
        key = (leg, v2, src)
        if key in seen_combo:
            continue
        seen_combo.add(key)
        samples.append({"legacy": leg, "v2": v2, "source": src})
    metrics["samples"] = samples[:10]

    total = len(jobs)
    legacy_keys = [str(j.get("JOB_KEY", "") or "").strip() or generate_job_key(j) for j in jobs]
    v2_keys = [str(j.get("JOB_KEY_V2", "")) for j in jobs]

    u_leg = len(set(legacy_keys))
    u_v2 = len(set(v2_keys))
    metrics["legacy_job_key_unique_count"] = u_leg
    metrics["v2_job_key_unique_count"] = u_v2
    metrics["legacy_collision_count"] = total - u_leg
    metrics["v2_collision_count"] = total - u_v2

    # ----- DEBUG: JOB_KEY_V2 collision groups (same V2 -> multiple jobs) -----
    collision_groups: dict[str, list[dict]] = {}
    for job in jobs:
        v2k = str(job.get("JOB_KEY_V2", "") or "").strip()
        if not v2k:
            continue
        collision_groups.setdefault(v2k, []).append(job)

    dup_groups = {k: v for k, v in collision_groups.items() if len(v) > 1}
    metrics["collision_group_count"] = len(dup_groups)
    metrics["largest_collision_group"] = (
        max(len(g) for g in dup_groups.values()) if dup_groups else 0
    )

    expected_gc = 0
    suspicious_gc = 0
    suspicious_by_url = 0
    suspicious_by_id_company = 0
    suspicious_by_hash_large = 0
    unclassified_gc = 0
    expected_collision_examples: list[dict] = []
    suspicious_collision_examples: list[dict] = []

    for v2k, group in dup_groups.items():
        if _is_expected_duplicate_collision_group(group):
            expected_gc += 1
            if len(expected_collision_examples) < 3:
                ex = _collision_example_payload(v2k, group)
                ex["classification"] = "expected_duplicate"
                expected_collision_examples.append(ex)
            continue

        tags = _suspicious_collision_rule_tags(group)
        if tags:
            suspicious_gc += 1
            if "S-URL" in tags:
                suspicious_by_url += 1
            if "S-ID-CO" in tags:
                suspicious_by_id_company += 1
            if "S-HASH-LARGE" in tags:
                suspicious_by_hash_large += 1
            if len(suspicious_collision_examples) < 5:
                ex = _collision_example_payload(v2k, group)
                ex["classification"] = "suspicious"
                ex["suspicious_rules"] = tags
                suspicious_collision_examples.append(ex)
        else:
            unclassified_gc += 1

    metrics["expected_duplicate_collision_groups"] = expected_gc
    metrics["suspicious_collision_groups"] = suspicious_gc
    metrics["suspicious_collision_by_url"] = suspicious_by_url
    metrics["suspicious_collision_by_id_company"] = suspicious_by_id_company
    metrics["suspicious_collision_by_hash_large"] = suspicious_by_hash_large
    metrics["collision_groups_unclassified"] = unclassified_gc
    metrics["expected_collision_examples"] = expected_collision_examples
    metrics["suspicious_collision_examples"] = suspicious_collision_examples

    sorted_dup = sorted(dup_groups.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    collision_examples: list[dict] = []
    for v2k, group in sorted_dup[:10]:
        src0 = str(group[0].get("identity_source", "") or "")
        collision_examples.append(
            {
                "job_key_v2": v2k,
                "identity_source": src0,
                "collision_size": len(group),
                "jobs": [
                    {
                        "source": str(j.get("source", "") or ""),
                        "company": str(j.get("company", "") or ""),
                        "title": str(j.get("title", "") or ""),
                        "link": str(j.get("link", "") or ""),
                    }
                    for j in group
                ],
            }
        )
    metrics["collision_examples"] = collision_examples

    return metrics


_TIER_MIX_ROWS = (
    ("v2_from_linkedin_id", "LinkedIn IDs"),
    ("v2_from_greenhouse_id", "Greenhouse IDs"),
    ("v2_from_lever_id", "Lever IDs"),
    ("v2_from_instahyre_id", "Instahyre IDs"),
    ("v2_from_canonical_url", "Canonical URLs"),
    ("v2_from_hash", "Hash Fallbacks"),
    ("v2_from_legacy", "Legacy Tier IDs"),
)


def _tier_pct(count: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round(100.0 * count / total, 1)


def log_job_identity_metrics(metrics: dict) -> None:
    """Production V2 identity + collision health (batch instrumentation)."""
    banner = "=" * 60
    rule = "-" * 60
    print(f"\n{banner}")
    print("   🆔 JOB IDENTITY HEALTH")
    print(banner)

    generated = int(metrics.get("v2_generated_count", 0))
    unique_v2 = int(metrics.get("v2_job_key_unique_count", 0))
    v2_collisions = int(metrics.get("v2_collision_count", 0))
    canon_changed = int(metrics.get("canonical_url_normalization_changed_count", 0))
    expected_dup = int(metrics.get("expected_duplicate_collision_groups", 0))
    suspicious = int(metrics.get("suspicious_collision_groups", 0))

    print()
    print(f"📌 V2 IDs Generated: {generated}")
    print(f"📌 Unique V2 Job Keys: {unique_v2}")
    print(f"📌 V2 Collision Count: {v2_collisions}")
    print(f"📌 Canonical URL Normalizations: {canon_changed}")

    print(f"\n{rule}")
    print("V2 ID TIER MIX")
    print(rule)
    print()
    for key, label in _TIER_MIX_ROWS:
        count = int(metrics.get(key, 0))
        pct = _tier_pct(count, generated)
        print(f"{label + ':':<18} {count:>5} ({pct:>5.1f}%)")

    print(f"\n{rule}\n")
    print(f"✅ Expected Duplicate Collision Groups: {expected_dup}")
    print(f"✅ Suspicious Collision Groups: {suspicious}")

    if debug_identity_enabled():
        print(f"\n{rule}")
        print("DEBUG IDENTITY METRICS")
        print(rule)
        print()
        print(f"Legacy Job Key Unique Count: {metrics.get('legacy_job_key_unique_count', 0)}")
        print(f"Legacy Collision Count: {metrics.get('legacy_collision_count', 0)}")
        print(f"Collision Group Count: {metrics.get('collision_group_count', 0)}")
        print(f"Largest Collision Group: {metrics.get('largest_collision_group', 0)}")
        print(
            f"Suspicious Collisions (URL): "
            f"{metrics.get('suspicious_collision_by_url', 0)}"
        )
        print(
            f"Suspicious Collisions (ID+Company): "
            f"{metrics.get('suspicious_collision_by_id_company', 0)}"
        )
        print(
            f"Suspicious Collisions (Large Hash): "
            f"{metrics.get('suspicious_collision_by_hash_large', 0)}"
        )
        print(
            f"Unclassified Collision Groups: "
            f"{metrics.get('collision_groups_unclassified', 0)}"
        )

        sus_ex = metrics.get("suspicious_collision_examples") or []
        if sus_ex:
            print("\nSuspicious collision samples:")
            for idx, ex in enumerate(sus_ex[:5], start=1):
                rules = ex.get("suspicious_rules") or []
                print(
                    f"  [{idx}] {', '.join(rules)} | "
                    f"KEY: {ex.get('job_key_v2', '')} | "
                    f"SIZE: {ex.get('collision_size', 0)}"
                )

        samples = metrics.get("samples") or []
        if samples:
            print("\nIdentity samples:")
            for idx, sample in enumerate(samples[:5], start=1):
                print(
                    f"  [{idx}] {sample.get('source', '')} | "
                    f"legacy={sample.get('legacy', '')} | v2={sample.get('v2', '')}"
                )

    print(f"\n{banner}\n")


def is_unresolved_identity(job: dict) -> bool:
    """
    Weak V2 tier: canonical_url, hash_fallback, or legacy_fallback (not tier-1 id).
    Observability only; does not change routing.
    """
    src = str(job.get("identity_source", "") or "").strip()
    return src not in _STRONG_IDENTITY_SOURCES


def _unresolved_source_bucket(job: dict) -> str:
    source = str(job.get("source", "") or "").strip().lower()
    if source == "linkedin":
        return "linkedin"
    if source == "greenhouse":
        return "greenhouse"
    if source == "lever":
        return "lever"
    if source == "instahyre":
        return "instahyre"
    return "other"


def snapshot_unresolved_segment(jobs: list[dict]) -> dict:
    """Count unresolved jobs in a pipeline cohort and bucket by scraper source."""
    total = len(jobs)
    unresolved = 0
    by_source = {k: 0 for k in _UNRESOLVED_SOURCE_BUCKETS}
    for job in jobs:
        if not is_unresolved_identity(job):
            continue
        unresolved += 1
        by_source[_unresolved_source_bucket(job)] += 1
    return {
        "total": total,
        "unresolved": unresolved,
        "unresolved_pct": round(100.0 * unresolved / total, 1) if total else 0.0,
        "by_source": by_source,
    }


def build_unresolved_identity_funnel(segments: dict[str, list[dict]]) -> dict:
    """
    Phase 6 funnel: unresolved counts at each pipeline checkpoint.

    Expected segment keys:
      unresolved_pre_stage1, unresolved_post_stage1, unresolved_survived_dedup,
      unresolved_ai_candidates, unresolved_final_recommendations
    """
    funnel: dict = {}
    for stage_key, job_list in segments.items():
        funnel[stage_key] = snapshot_unresolved_segment(job_list)
    final = funnel.get("unresolved_final_recommendations") or {}
    funnel["unresolved_identity_count"] = int(final.get("unresolved", 0))
    return funnel


def collect_phase6_continuity_metrics(jobs: list[dict]) -> dict:
    """Cross-query / recruiter signals for Phase 6 summary (observability only)."""
    v2_to_query_ids: dict[str, set[str]] = {}
    recruiter_with_v2 = 0
    v2_total = 0
    not_specified = frozenset({"", "not specified", "unknown", "n/a", "na", "none"})

    for job in jobs:
        v2 = str(job.get("JOB_KEY_V2", "") or "").strip()
        if not v2:
            continue
        v2_total += 1
        qid = str(job.get("linkedin_query_id", "") or "").strip()
        if qid:
            v2_to_query_ids.setdefault(v2, set()).add(qid)
        hm = str(job.get("hiring_manager", "") or "").strip().lower()
        if hm not in not_specified:
            recruiter_with_v2 += 1

    cross_query_same_v2 = sum(
        1 for qs in v2_to_query_ids.values() if len(qs) > 1
    )
    return {
        "cross_query_same_v2_count": cross_query_same_v2,
        "jobs_with_v2_count": v2_total,
        "recruiter_specified_on_v2_jobs": recruiter_with_v2,
        "recruiter_presence_rate_on_v2": (
            round(recruiter_with_v2 / v2_total, 3) if v2_total else 0.0
        ),
    }


def debug_identity_enabled() -> bool:
    return os.environ.get("DEBUG_IDENTITY", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


_FUNNEL_STAGE_LABELS = (
    ("unresolved_pre_stage1", "Before Stage 1"),
    ("unresolved_post_stage1", "After Stage 1"),
    ("unresolved_survived_dedup", "After Dedup"),
    ("unresolved_ai_candidates", "AI Candidate Pool"),
    ("unresolved_final_recommendations", "Final Recommendations"),
)

_SOURCE_DISPLAY_LABELS = {
    "linkedin": "LinkedIn",
    "greenhouse": "Greenhouse",
    "lever": "Lever",
    "instahyre": "Instahyre",
    "other": "Other",
}


def _format_funnel_row(label: str, unresolved: int, total: int, pct: float) -> str:
    return f"{label:<28} {unresolved:>4} / {total:<4} ({pct:>5.1f}%)"


def log_routing_lookup_summary(trace: dict | None) -> None:
    """Lightweight routing-time view of historical V2 vs legacy lookup (read-only)."""
    trace = trace or {}
    lookup_calls = int(trace.get("historical_lookup_calls", 0))
    if lookup_calls <= 0:
        return

    v2_hits = int(trace.get("historical_lookup_v2_index_hit", 0))
    legacy_hits = int(trace.get("historical_lookup_legacy_fallback_hit", 0))
    legacy_rescue = int(
        trace.get("historical_lookup_v2_miss_legacy_recover_hit", 0)
    )
    no_match = int(trace.get("historical_lookup_legacy_fallback_miss", 0))

    print("\n--- Historical lookup stats (routing) ---")
    print(f"  Lookups: {lookup_calls}")
    print(f"  V2 index hits: {v2_hits}")
    print(f"  Legacy fallback hits: {legacy_hits}")
    print(f"  V2 miss → legacy recover: {legacy_rescue}")
    if no_match > 0:
        print(f"  No match: {no_match}")
    print("  Scope: intake-wide (all scraped jobs at historical lookup)")


def log_compact_unresolved_summary(title: str, segment: dict | None) -> None:
    """Compact unresolved identity block for operators (intake or checkpoint)."""
    segment = segment or {}
    total = int(segment.get("total", 0))
    unresolved = int(segment.get("unresolved", 0))
    pct = float(segment.get("unresolved_pct", 0.0) or 0.0)
    if total and not pct:
        pct = round(100.0 * unresolved / total, 1)

    by_source = segment.get("by_source") or {}
    print(f"\n--- {title} unresolved identity ---")
    print(f"  Unresolved: {unresolved} / {total} ({pct}%)")
    parts = []
    for bucket in _UNRESOLVED_SOURCE_BUCKETS:
        label = _SOURCE_DISPLAY_LABELS.get(bucket, bucket.title())
        count = int(by_source.get(bucket, 0))
        parts.append(f"{label} {count}")
    print(f"  By source: {' | '.join(parts)}")
    if int(by_source.get("other", 0)) > 0:
        print("  Other bucket = weak/non-tier V2 sources (see identity_source)")


def log_production_identity_health_summary(
    *,
    identity_metrics: dict,
    historical_lookup_trace: dict | None,
    dedup_observability: dict | None,
    historical_upsert_trace: dict | None,
    continuity_metrics: dict | None,
    unresolved_funnel: dict | None = None,
    final_recommendation_count: int = 0,
    final_dedup_removed: int = 0,
) -> None:
    """Post-run production identity health (V2-first routing)."""
    banner = "=" * 60
    rule = "-" * 60
    print(f"\n{banner}")
    print("   PRODUCTION IDENTITY HEALTH")
    print(banner)

    historical_lookup_trace = historical_lookup_trace or {}
    dedup_observability = dedup_observability or {}
    historical_upsert_trace = historical_upsert_trace or {}
    continuity_metrics = continuity_metrics or {}
    unresolved_funnel = unresolved_funnel or {}

    lookup_calls = int(historical_lookup_trace.get("historical_lookup_calls", 0))
    v2_hits = int(historical_lookup_trace.get("historical_lookup_v2_index_hit", 0))
    legacy_rescue = int(
        historical_lookup_trace.get("historical_lookup_v2_miss_legacy_recover_hit", 0)
    )
    if lookup_calls:
        historical_v2_hit_pct = round(100.0 * v2_hits / lookup_calls, 1)
        legacy_rescue_pct = round(100.0 * legacy_rescue / lookup_calls, 1)
    else:
        historical_v2_hit_pct = 0.0
        legacy_rescue_pct = 0.0

    unresolved_identity_count = int(
        unresolved_funnel.get(
            "unresolved_identity_count",
            (unresolved_funnel.get("unresolved_final_recommendations") or {}).get(
                "unresolved", 0
            ),
        )
    )

    historical_upsert_v2_refresh = int(
        historical_upsert_trace.get("historical_upsert_v2_refresh", 0)
    )
    historical_upsert_v2_new_row = int(
        historical_upsert_trace.get("historical_upsert_v2_new_row", 0)
    )
    recruiter_presence_rate = float(
        continuity_metrics.get("recruiter_presence_rate_on_v2", 0.0) or 0.0
    )
    recruiter_coverage_pct = round(recruiter_presence_rate * 100.0, 1)

    final_seg = unresolved_funnel.get("unresolved_final_recommendations") or {}
    final_unresolved = int(final_seg.get("unresolved", 0))
    final_total = int(final_seg.get("total", final_recommendation_count) or 0)
    final_unresolved_pct = float(final_seg.get("unresolved_pct", 0.0) or 0.0)
    if final_total and not final_unresolved_pct:
        final_unresolved_pct = round(100.0 * final_unresolved / final_total, 1)

    print()
    print(f"📌 Final Recommendation Count: {final_recommendation_count}")
    print(f"📌 Historical V2 Hit Rate: {historical_v2_hit_pct}%")
    print(f"📌 Legacy Rescue Rate: {legacy_rescue_pct}%")
    print(
        "  Scope: export cohort only (final recommendations); "
        "compare to routing lookup stats above"
    )
    print(f"📌 Unresolved Identity Count: {unresolved_identity_count}")
    print(
        f"📌 Historical V2 Upserts: refresh={historical_upsert_v2_refresh} "
        f"new_row={historical_upsert_v2_new_row}"
    )
    print(f"📌 Recruiter Coverage Rate: {recruiter_coverage_pct}%")
    print()
    print(
        f"⚠️ Unresolved Final Recommendations: "
        f"{final_unresolved} / {final_total} ({final_unresolved_pct}%)"
    )

    if debug_identity_enabled():
        print(f"\n{rule}")
        print("UNRESOLVED IDENTITY FUNNEL")
        print(rule)
        print()
        for stage_key, label in _FUNNEL_STAGE_LABELS:
            seg = unresolved_funnel.get(stage_key) or {}
            u = int(seg.get("unresolved", 0))
            t = int(seg.get("total", 0))
            pct = float(seg.get("unresolved_pct", 0.0) or 0.0)
            if t and not pct:
                pct = round(100.0 * u / t, 1)
            print(_format_funnel_row(label, u, t, pct))

    final_by = final_seg.get("by_source") or {}
    print(f"\n{rule}")
    print("UNRESOLVED BY SOURCE")
    print(rule)
    print()
    for bucket in _UNRESOLVED_SOURCE_BUCKETS:
        display = _SOURCE_DISPLAY_LABELS.get(bucket, bucket.title())
        print(f"{display:<14} {int(final_by.get(bucket, 0))}")

    if debug_identity_enabled():
        v2_dedup_hits = int(dedup_observability.get("v2_dedup_hits", 0))
        exact_hits = int(dedup_observability.get("exact_dedup_hits", 0))
        fuzzy_hits = int(dedup_observability.get("fuzzy_dedup_hits", 0))
        cross_query_same_v2_count = int(
            continuity_metrics.get("cross_query_same_v2_count", 0)
        )
        suspicious_collision_groups = int(
            identity_metrics.get("suspicious_collision_groups", 0)
        )
        print(f"\n{rule}")
        print("DEBUG IDENTITY METRICS")
        print(rule)
        print()
        print(f"Final Merge Authority: v2_only")
        print(f"Final Merge Dedup Removed: {final_dedup_removed}")
        print(f"Dedup V2 Hits: {v2_dedup_hits}")
        print(f"Dedup Exact Hits: {exact_hits}")
        print(f"Dedup Fuzzy Hits: {fuzzy_hits}")
        print(f"Cross-Query Same V2 Count: {cross_query_same_v2_count}")
        print(f"Suspicious Collision Groups: {suspicious_collision_groups}")

    print(f"\n{banner}\n")


def strip_job_identity_v2_fields(job: dict) -> None:
    """Remove Phase 0 fields before CSV export (no schema change)."""
    job.pop("JOB_KEY_V2", None)
    job.pop("identity_source", None)
