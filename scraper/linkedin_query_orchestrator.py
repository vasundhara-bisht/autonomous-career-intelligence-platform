"""
LinkedIn multi-strategy query orchestration (acquisition intelligence only).

Loads config/linkedin_queries.json, selects queries with bucket weights + cooldown,
runs existing scrape_linkedin_jobs traversal, tags jobs with query metadata, and
prints concise LINKEDIN QUERY RUN SUMMARY blocks.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

from agent.filter_engine import apply_stage1_filter
from scraper.acquisition_gate import effective_session_cap
from scraper.linkedin import debug_linkedin_enabled

import paths

_ROOT = paths.REPO_ROOT
_CONFIG_PATH = paths.linkedin_queries_json()
_STATE_PATH = paths.linkedin_query_state_json()

_NOT_SPECIFIED = frozenset(
    {"", "not specified", "unknown", "n/a", "na", "none"}
)


@dataclass
class QueryDefinition:
    id: str
    label: str
    query_group: str
    keywords: str
    location: str
    filter_profile: str
    url: str
    domain_sub: str | None = None
    company: str | None = None
    url_mode: str | None = None
    navigation: dict | None = None


@dataclass
class QueryRunMetrics:
    """Computed per-run counters (no query identity — use QueryRunResult for summaries)."""

    jobs_collected: int = 0
    unique_v2_new: int = 0
    unique_v2_total_run: int = 0
    overlap_ratio: float = 0.0
    stage1_accepted: int = 0
    recruiter_specified: int = 0
    hiring_manager_rate: float = 0.0
    recruiter_presence_rate: float = 0.0


@dataclass
class QueryRunResult:
    query_id: str
    query_group: str
    label: str
    filter_profile: str
    jobs_collected: int = 0
    unique_v2_new: int = 0
    unique_v2_total_run: int = 0
    overlap_ratio: float = 0.0
    stage1_accepted: int = 0
    recruiter_specified: int = 0
    hiring_manager_rate: float = 0.0
    recruiter_presence_rate: float = 0.0
    duration_sec: float = 0.0
    error: str | None = None


def build_query_run_result(
    query: QueryDefinition,
    metrics: QueryRunMetrics,
    *,
    duration_sec: float = 0.0,
    error: str | None = None,
) -> QueryRunResult:
    """Single construction path for a complete QueryRunResult."""
    return QueryRunResult(
        query_id=query.id,
        query_group=query.query_group,
        label=query.label,
        filter_profile=query.filter_profile,
        jobs_collected=metrics.jobs_collected,
        unique_v2_new=metrics.unique_v2_new,
        unique_v2_total_run=metrics.unique_v2_total_run,
        overlap_ratio=metrics.overlap_ratio,
        stage1_accepted=metrics.stage1_accepted,
        recruiter_specified=metrics.recruiter_specified,
        hiring_manager_rate=metrics.hiring_manager_rate,
        recruiter_presence_rate=metrics.recruiter_presence_rate,
        duration_sec=duration_sec,
        error=error,
    )


def _load_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _save_state(state: dict) -> None:
    with open(_STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def _load_state_from_db() -> dict | None:
    try:
        from db.bootstrap import ensure_database_ready
        from db.engine import get_session
        from db.models.schema import QueryCooldownState
        from db.read.engine import query_state_read_enabled
        from sqlalchemy import select

        if not query_state_read_enabled():
            return None

        ensure_database_ready()
        with get_session() as session:
            rows = list(session.execute(select(QueryCooldownState)).scalars().all())
        if not rows:
            return None
        last_run: dict[str, float] = {}
        domain_rotation_index = 0
        for row in rows:
            if row.last_run_at is not None:
                last_run[str(row.query_id)] = float(row.last_run_at)
            if row.domain_rotation_index is not None:
                domain_rotation_index = int(row.domain_rotation_index)
        return {
            "last_run_by_query_id": last_run,
            "domain_rotation_index": domain_rotation_index,
        }
    except Exception:
        return None


def _load_state() -> dict:
    db_state = _load_state_from_db()
    if db_state is not None:
        print("  LinkedIn query state: SQLite (SQLITE_QUERY_STATE_READ=1)")
        return db_state
    if not _STATE_PATH.exists():
        return {"last_run_by_query_id": {}, "domain_rotation_index": 0}
    try:
        return _load_json(_STATE_PATH)
    except (json.JSONDecodeError, OSError):
        return {"last_run_by_query_id": {}, "domain_rotation_index": 0}


def build_linkedin_search_url(
    *,
    keywords: str,
    location: str,
    filter_profile: str,
    filter_profiles: dict,
    company: str | None = None,
) -> str:
    params: dict[str, str] = {
        "keywords": keywords,
        "location": location,
    }
    prof = filter_profiles.get(filter_profile) or filter_profiles.get("baseline") or {}
    for k, v in prof.items():
        params[k] = str(v)
    if company:
        params["keywords"] = f"{company} {keywords}".strip()
    return "https://www.linkedin.com/jobs/search/?" + urlencode(params)


_LANDING_URL_MODES = frozenset({"qualification_landing", "search_results_landing"})
_DEFAULT_QUALIFICATION_ENTRY_URL = "https://www.linkedin.com/jobs/"


def resolve_query_url(q: dict, filter_profiles: dict) -> str:
    """Build scrape URL for a catalog entry (search builder or fixed landing URL)."""
    url_mode = str(q.get("url_mode", "") or "").strip()
    if url_mode in _LANDING_URL_MODES:
        env_key = (
            "LINKEDIN_QUALIFICATION_LANDING_URL"
            if url_mode == "qualification_landing"
            else "LINKEDIN_BROAD_PM_LANDING_URL"
        )
        url = os.environ.get(env_key, "").strip()
        if url:
            return url
        if url_mode == "qualification_landing":
            nav = q.get("navigation")
            if isinstance(nav, dict) and nav:
                entry = str(nav.get("entry_url", "") or "").strip()
                return entry or _DEFAULT_QUALIFICATION_ENTRY_URL
        url = str(q.get("landing_url", "")).strip()
        if not url:
            raise ValueError(
                f"{url_mode} query {q.get('id', '?')!r} missing landing_url"
            )
        return url
    return build_linkedin_search_url(
        keywords=str(q.get("keywords", "")),
        location=str(q.get("location", "India")),
        filter_profile=str(q.get("filter_profile", "baseline")),
        filter_profiles=filter_profiles,
        company=q.get("company"),
    )


def load_query_catalog(config_path: Path | None = None) -> tuple[dict, list[QueryDefinition]]:
    cfg = _load_json(config_path or _CONFIG_PATH)
    fps = cfg.get("filter_profiles") or {}
    out: list[QueryDefinition] = []
    for q in cfg.get("queries") or []:
        if not q.get("enabled", True):
            continue
        url_mode = str(q.get("url_mode", "") or "").strip() or None
        nav_raw = q.get("navigation")
        navigation = nav_raw if isinstance(nav_raw, dict) and nav_raw else None
        url = resolve_query_url(q, fps)
        out.append(
            QueryDefinition(
                id=str(q["id"]),
                label=str(q.get("label", q["id"])),
                query_group=str(q.get("query_group", "unknown")),
                keywords=str(q.get("keywords", "")),
                location=str(q.get("location", "")),
                filter_profile=str(q.get("filter_profile", "baseline")),
                url=url,
                domain_sub=q.get("domain_sub"),
                company=q.get("company"),
                url_mode=url_mode,
                navigation=navigation,
            )
        )
    return cfg, out


def _recruiter_specified(job: dict) -> bool:
    hm = str(job.get("hiring_manager") or "").strip().lower()
    return hm not in _NOT_SPECIFIED


def _compute_run_metrics(
    jobs: list[dict],
    seen_v2_global: set[str],
) -> tuple[QueryRunMetrics, set[str]]:
    """Return computed counters; combine with QueryDefinition via build_query_run_result."""
    from agent.job_identity import generate_job_key_v2

    new_v2: set[str] = set()
    stage1_ok = 0
    recruiter_n = 0

    for job in jobs:
        v2, _ = generate_job_key_v2(job)
        if v2:
            new_v2.add(v2)
        if _recruiter_specified(job):
            recruiter_n += 1
        s1 = apply_stage1_filter(dict(job))
        if s1 and not s1.get("rejected"):
            stage1_ok += 1

    unique_new = len(new_v2 - seen_v2_global)
    total_run = len(new_v2)
    collected = len(jobs)
    overlap = 0.0
    if collected > 0:
        overlap = max(0.0, 1.0 - (unique_new / collected))

    hm_rate = (recruiter_n / collected) if collected else 0.0

    metrics = QueryRunMetrics(
        jobs_collected=collected,
        unique_v2_new=unique_new,
        unique_v2_total_run=total_run,
        overlap_ratio=round(overlap, 3),
        stage1_accepted=stage1_ok,
        recruiter_specified=recruiter_n,
        hiring_manager_rate=round(hm_rate, 3),
        recruiter_presence_rate=round(hm_rate, 3),
    )
    return metrics, new_v2


def print_query_run_summary(result: QueryRunResult) -> None:
    if result.error:
        print(f"❌ Query failed: {result.label} — {result.error}\n")
        return

    recruiter_pct = round(float(result.recruiter_presence_rate or 0) * 100.0, 1)
    print(f"✅ Query Jobs Collected: {result.jobs_collected}")
    print(f"✅ Unique V2 Jobs: {result.unique_v2_total_run}")
    print(f"✅ Stage 1 Accepted: {result.stage1_accepted}")
    print(f"✅ Recruiter Coverage Rate: {recruiter_pct}%")
    print()


def _print_session_plan(picks: list[QueryDefinition], plan_trace: dict) -> None:
    if debug_linkedin_enabled():
        print(f"\n[debug] Session plan: {len(picks)} run(s)")
        start_idx = 0
        if plan_trace.get("priority_anchor_ran"):
            aq = picks[0]
            print(
                f"  [debug] [PRIORITY_ANCHOR] {aq.label} ({aq.id}) "
                f"source={plan_trace.get('priority_anchor_source', '')}"
            )
            start_idx = 1
        else:
            reason = plan_trace.get("priority_anchor_skip_reason") or "n/a"
            print(f"  [debug] [PRIORITY_ANCHOR] skipped ({reason})")
        followup_id = plan_trace.get("priority_followup_query_id") or ""
        if followup_id and start_idx < len(picks) and picks[start_idx].id == followup_id:
            fq = picks[start_idx]
            print(
                f"  [debug] [PRIORITY_FOLLOWUP] {fq.label} ({fq.id})"
            )
            start_idx += 1
        elif followup_id and plan_trace.get("priority_followup_ran"):
            print(f"  [debug] [PRIORITY_FOLLOWUP] {followup_id} (not first orchestrated slot)")
        elif followup_id:
            print("  [debug] [PRIORITY_FOLLOWUP] skipped (cooldown or no orchestrated slot)")
        for i, q in enumerate(picks[start_idx:], start=start_idx + 1):
            print(f"  [debug] {i}. [{q.query_group}] {q.label} ({q.id})")
        print()


def _cooldown_elapsed(last_ts: float, cooldown_hours: float) -> bool:
    return (time.time() - last_ts) >= (cooldown_hours * 3600.0)


def _env_disabled(name: str) -> bool:
    v = os.environ.get(name, "").strip().lower()
    return v in ("0", "false", "no", "off")


def _catalog_by_id(catalog: list[QueryDefinition]) -> dict[str, QueryDefinition]:
    return {q.id: q for q in catalog}


def _resolve_query_from_catalog(
    catalog: list[QueryDefinition],
    query_id: str,
) -> QueryDefinition | None:
    if not query_id:
        return None
    return _catalog_by_id(catalog).get(query_id)


def resolve_priority_anchor(
    catalog: list[QueryDefinition],
    cfg: dict,
    *,
    last_run: dict[str, float],
    cooldown_hours: float,
) -> tuple[QueryDefinition | None, dict]:
    """
    Resolve deterministic session anchor (runs first; does not consume bucket slots).

    Returns (query_or_none, trace_dict).
    """
    trace: dict = {
        "priority_anchor_enabled": False,
        "priority_anchor_query_id": "",
        "priority_anchor_source": "skipped",
        "priority_anchor_skip_reason": "",
    }
    anchor_cfg = (cfg.get("defaults") or {}).get("priority_anchor") or {}
    if _env_disabled("LINKEDIN_PRIORITY_ANCHOR"):
        trace["priority_anchor_skip_reason"] = "env_disabled"
        return None, trace

    if not anchor_cfg.get("enabled", True):
        trace["priority_anchor_skip_reason"] = "config_disabled"
        return None, trace

    trace["priority_anchor_enabled"] = True
    query_id = os.environ.get("LINKEDIN_PRIORITY_ANCHOR_ID", "").strip() or str(
        anchor_cfg.get("query_id", "")
    ).strip()
    trace["priority_anchor_query_id"] = query_id

    bypass = bool(anchor_cfg.get("bypass_cooldown", True))
    fallback_id = str(anchor_cfg.get("fallback_query_id", "") or "").strip()
    fallback_on_cooldown = bool(anchor_cfg.get("fallback_if_anchor_on_cooldown", True))
    fallback_if_missing = bool(
        anchor_cfg.get("fallback_if_anchor_disabled_in_catalog", True)
    )

    def _pick(qid: str) -> QueryDefinition | None:
        q = _resolve_query_from_catalog(catalog, qid)
        if q is None:
            return None
        return q

    primary = _pick(query_id)
    if primary is None and fallback_if_missing and fallback_id:
        primary = _pick(fallback_id)
        if primary:
            trace["priority_anchor_source"] = "fallback_missing_primary"
            trace["priority_anchor_query_id"] = primary.id
            return primary, trace
        trace["priority_anchor_skip_reason"] = "not_found"
        return None, trace

    if primary is None:
        trace["priority_anchor_skip_reason"] = "not_found"
        return None, trace

    last = last_run.get(primary.id, 0)
    on_cooldown = bool(last) and not _cooldown_elapsed(last, cooldown_hours)
    if on_cooldown and not bypass:
        if fallback_on_cooldown and fallback_id and fallback_id != primary.id:
            fb = _pick(fallback_id)
            if fb:
                trace["priority_anchor_source"] = "fallback_cooldown"
                trace["priority_anchor_query_id"] = fb.id
                return fb, trace
        trace["priority_anchor_skip_reason"] = "cooldown"
        return None, trace

    trace["priority_anchor_source"] = "primary"
    trace["priority_anchor_query_id"] = primary.id
    return primary, trace


def resolve_priority_followup(
    catalog: list[QueryDefinition],
    cfg: dict,
    *,
    last_run: dict[str, float],
    cooldown_hours: float,
    exclude_ids: set[str] | None = None,
) -> QueryDefinition | None:
    """Fixed second query after priority anchor when session budget allows."""
    if _env_disabled("LINKEDIN_PRIORITY_FOLLOWUP"):
        return None
    followup_cfg = (cfg.get("defaults") or {}).get("priority_followup") or {}
    if not followup_cfg.get("enabled"):
        return None
    query_id = str(followup_cfg.get("query_id", "") or "").strip()
    if not query_id:
        return None
    followup = _resolve_query_from_catalog(catalog, query_id)
    if not followup:
        return None
    if exclude_ids and followup.id in exclude_ids:
        return None
    bypass = bool(followup_cfg.get("bypass_cooldown", True))
    last = last_run.get(followup.id, 0)
    on_cooldown = bool(last) and not _cooldown_elapsed(last, cooldown_hours)
    if on_cooldown and not bypass:
        return None
    return followup


def build_session_query_plan(
    catalog: list[QueryDefinition],
    cfg: dict,
    *,
    max_runs: int | None = None,
) -> tuple[list[QueryDefinition], dict]:
    """
    Anchor first (if resolved), then weighted orchestration for the remainder.
    Anchor does not consume bucket slots; may reduce orchestrated pick count when
    counts_toward_max_runs is true.
    """
    defaults = cfg.get("defaults") or {}
    session_max = effective_session_cap(
        max_runs,
        int(defaults.get("max_runs_per_session", 5)),
    )
    if session_max <= 0:
        return [], {"session_max_runs": 0, "priority_anchor_ran": 0}
    cooldown_h = float(defaults.get("cooldown_hours", 72))
    anchor_cfg = defaults.get("priority_anchor") or {}
    counts_toward_max = bool(anchor_cfg.get("counts_toward_max_runs", True))

    state = _load_state()
    last_run = state.setdefault("last_run_by_query_id", {})

    anchor, anchor_trace = resolve_priority_anchor(
        catalog, cfg, last_run=last_run, cooldown_hours=cooldown_h
    )

    orchestrated_max = session_max
    if anchor and counts_toward_max:
        orchestrated_max = max(0, session_max - 1)

    exclude_ids = {anchor.id} if anchor else set()
    followup = resolve_priority_followup(
        catalog,
        cfg,
        last_run=last_run,
        cooldown_hours=cooldown_h,
        exclude_ids=exclude_ids,
    )

    if orchestrated_max > 0:
        bucket_runs = orchestrated_max
        if followup:
            bucket_runs = max(0, orchestrated_max - 1)
        orchestrated = (
            select_queries_for_session(catalog, cfg, max_runs=bucket_runs)
            if bucket_runs > 0
            else []
        )
        if followup:
            orchestrated = [followup] + [
                q for q in orchestrated if q.id != followup.id
            ]
            orchestrated = orchestrated[:orchestrated_max]
    else:
        orchestrated = []

    picks: list[QueryDefinition] = []
    if anchor:
        picks.append(anchor)
    seen_ids = {q.id for q in picks}
    for q in orchestrated:
        if q.id in seen_ids:
            continue
        picks.append(q)
        seen_ids.add(q.id)

    plan_trace = dict(anchor_trace)
    plan_trace["session_max_runs"] = session_max
    plan_trace["orchestrated_max_runs"] = orchestrated_max
    plan_trace["priority_anchor_ran"] = 1 if anchor else 0
    plan_trace["priority_followup_ran"] = (
        1 if followup and any(q.id == followup.id for q in orchestrated) else 0
    )
    plan_trace["priority_followup_query_id"] = followup.id if followup else ""
    if counts_toward_max:
        return picks[:session_max], plan_trace
    return picks, plan_trace


def _bucket_slots(
    max_runs: int,
    weights: dict[str, float],
    bucket_max_slots: dict[str, int] | None = None,
) -> dict[str, int]:
    """Allocate integer run slots per bucket from weights."""
    caps = bucket_max_slots or {}
    groups = list(weights.keys())
    raw = {g: weights[g] * max_runs for g in groups}
    slots = {g: int(raw[g]) for g in groups}
    remainder = max_runs - sum(slots.values())
    order = sorted(groups, key=lambda g: raw[g] - slots[g], reverse=True)
    i = 0
    while remainder > 0 and order:
        slots[order[i % len(order)]] += 1
        remainder -= 1
        i += 1
    for g, cap in caps.items():
        if g in slots:
            slots[g] = min(slots[g], int(cap))
    shortfall = max_runs - sum(slots.values())
    if shortfall > 0:
        fill_order = sorted(
            groups,
            key=lambda g: weights.get(g, 0),
            reverse=True,
        )
        j = 0
        attempts = 0
        max_attempts = max(len(fill_order) * 4, 8)
        while shortfall > 0 and fill_order and attempts < max_attempts:
            attempts += 1
            g = fill_order[j % len(fill_order)]
            j += 1
            cap = caps.get(g)
            if cap is not None and slots.get(g, 0) >= int(cap):
                continue
            slots[g] = slots.get(g, 0) + 1
            shortfall -= 1
    return slots


def select_queries_for_session(
    catalog: list[QueryDefinition],
    cfg: dict,
    *,
    max_runs: int | None = None,
) -> list[QueryDefinition]:
    defaults = cfg.get("defaults") or {}
    max_runs = effective_session_cap(
        max_runs,
        int(defaults.get("max_runs_per_session", 5)),
    )
    cooldown_h = float(defaults.get("cooldown_hours", 72))
    weights = defaults.get("bucket_weights") or {}
    domain_weights = defaults.get("domain_pm_weights") or {}
    domain_order = defaults.get("domain_pm_rotation_order") or []

    state = _load_state()
    last_run = state.setdefault("last_run_by_query_id", {})
    slots = _bucket_slots(
        max_runs,
        weights,
        defaults.get("bucket_max_slots"),
    )

    by_group: dict[str, list[QueryDefinition]] = {}
    for q in catalog:
        by_group.setdefault(q.query_group, []).append(q)

    selected: list[QueryDefinition] = []

    def pick_from_group(group: str, n: int) -> None:
        pool = [q for q in by_group.get(group, []) if q.query_group == group]
        if not pool:
            return

        if group == "domain_pm" and domain_order:
            rot = int(state.get("domain_rotation_index", 0))
            subs = [s for s in domain_order if any(q.domain_sub == s for q in pool)]
            preferred_sub = subs[rot % len(subs)] if subs else None
            if preferred_sub:
                weighted = [
                    q
                    for q in pool
                    if q.domain_sub == preferred_sub
                    or (q.domain_sub or "") not in domain_weights
                ]
                if weighted:
                    pool = weighted
            state["domain_rotation_index"] = rot + 1

        def sort_key(q: QueryDefinition) -> tuple:
            last = last_run.get(q.id, 0)
            on_cooldown = 0 if _cooldown_elapsed(last, cooldown_h) else 1
            w = domain_weights.get(q.domain_sub or "", 1.0) if group == "domain_pm" else 1.0
            return (on_cooldown, -w, last)

        pool.sort(key=sort_key)
        taken = 0
        for q in pool:
            if taken >= n:
                break
            last = last_run.get(q.id, 0)
            if last and not _cooldown_elapsed(last, cooldown_h):
                continue
            selected.append(q)
            taken += 1

    bucket_caps = defaults.get("bucket_max_slots") or {}

    def _group_selected_count(group: str) -> int:
        return sum(1 for q in selected if q.query_group == group)

    for group, n in slots.items():
        if n > 0:
            pick_from_group(group, n)

    if len(selected) < max_runs:
        remaining = [q for q in catalog if q not in selected]
        remaining.sort(
            key=lambda q: (
                -weights.get(q.query_group, 0),
                last_run.get(q.id, 0),
            )
        )
        for q in remaining:
            if len(selected) >= max_runs:
                break
            cap = bucket_caps.get(q.query_group)
            if cap is not None and _group_selected_count(q.query_group) >= int(cap):
                continue
            last = last_run.get(q.id, 0)
            if last and not _cooldown_elapsed(last, cooldown_h):
                continue
            selected.append(q)

    _save_state(state)
    return selected[:max_runs]


def stamp_jobs_with_query_metadata(
    jobs: list[dict],
    query: QueryDefinition,
    *,
    query_role: str = "orchestrated",
) -> None:
    ts = datetime.now(timezone.utc).isoformat()
    for job in jobs:
        job["linkedin_query_id"] = query.id
        job["linkedin_query_group"] = query.query_group
        job["linkedin_query_label"] = query.label
        job["linkedin_filter_profile"] = query.filter_profile
        job["linkedin_query_role"] = query_role
        job["linkedin_run_ts"] = ts
        if query.domain_sub:
            job["linkedin_domain_sub"] = query.domain_sub
        if query.company:
            job["linkedin_company_watch"] = query.company


def run_linkedin_acquisition_session(
    scrape_fn,
    *,
    max_runs: int | None = None,
    config_path: Path | None = None,
    inter_run_pause_sec: tuple[int, int] = (90, 180),
) -> list[dict]:
    """
    Run a full orchestrated LinkedIn session. ``scrape_fn(url, query_run=...)`` must
    return a list of job dicts (see scrape_linkedin_jobs).
    """
    import random

    if max_runs is not None and int(max_runs) <= 0:
        return []

    cfg, catalog = load_query_catalog(config_path)
    allow_ids: set[str] | None = None
    if os.environ.get("LINKEDIN_QUERY_IDS", "").strip():
        allow_ids = {
            x.strip() for x in os.environ["LINKEDIN_QUERY_IDS"].split(",") if x.strip()
        }
        catalog = [q for q in catalog if q.id in allow_ids]

    anchor_cfg = (cfg.get("defaults") or {}).get("priority_anchor") or {}
    anchor_query_id = str(anchor_cfg.get("query_id", "") or "").strip()
    if allow_ids and anchor_query_id and anchor_query_id not in allow_ids:
        anchor_catalog = load_query_catalog(config_path)[1]
        anchor_only = [q for q in anchor_catalog if q.id == anchor_query_id]
        if anchor_only:
            catalog = anchor_only + [q for q in catalog if q.id != anchor_query_id]

    picks, plan_trace = build_session_query_plan(catalog, cfg, max_runs=max_runs)
    if not picks:
        print("⏭️ LinkedIn: no queries selected (cooldown or empty catalog).")
        return []

    print("\n🟦 LINKEDIN ACQUISITION STARTED\n")
    _print_session_plan(picks, plan_trace)

    state = _load_state()
    last_run = state.setdefault("last_run_by_query_id", {})
    seen_v2_global: set[str] = set()
    all_jobs: list[dict] = []
    session_results: list[QueryRunResult] = []
    anchor_v2_new = 0

    for i, query in enumerate(picks):
        if i > 0:
            pause = random.randint(inter_run_pause_sec[0], inter_run_pause_sec[1])
            if debug_linkedin_enabled():
                print(f"[debug] Inter-run pause {pause}s (humanized spacing)")
            time.sleep(pause)

        print(f"🔵 Query: {query.label}")
        print(f"🔵 Query ID: {query.id}\n")

        query_run = {
            "query_id": query.id,
            "query_group": query.query_group,
            "label": query.label,
            "filter_profile": query.filter_profile,
        }
        if (
            query.url_mode == "qualification_landing"
            and query.navigation
            and not os.environ.get("LINKEDIN_QUALIFICATION_LANDING_URL", "").strip()
        ):
            query_run["qualification_navigation"] = query.navigation
        t0 = time.monotonic()
        err = None
        jobs: list[dict] = []
        role = (
            "priority_anchor"
            if plan_trace.get("priority_anchor_ran") and i == 0
            else "orchestrated"
        )
        try:
            jobs = scrape_fn(query.url, query_run=query_run)
            stamp_jobs_with_query_metadata(jobs, query, query_role=role)
        except Exception as e:
            err = repr(e)

        metrics, new_v2 = _compute_run_metrics(jobs, seen_v2_global)
        seen_v2_global |= new_v2
        if role == "priority_anchor":
            anchor_v2_new = metrics.unique_v2_new

        result = build_query_run_result(
            query,
            metrics,
            duration_sec=time.monotonic() - t0,
            error=err,
        )
        print_query_run_summary(result)
        session_results.append(result)
        all_jobs.extend(jobs)
        last_run[query.id] = time.time()

    _save_state(state)

    total_new = sum(r.unique_v2_new for r in session_results)
    total_collected = sum(r.jobs_collected for r in session_results)
    avg_overlap = (
        sum(r.overlap_ratio for r in session_results) / len(session_results)
        if session_results
        else 0.0
    )
    best = max(session_results, key=lambda r: r.unique_v2_new, default=None)

    print("\n🟦 LINKEDIN SESSION COMPLETE\n")
    print(f"✅ Runs Executed: {len(session_results)}")
    print(f"✅ Total Jobs Collected: {total_collected}")
    print(f"✅ Total Unique V2 Jobs: {total_new}")
    if best:
        print(f"✅ Best Query: {best.query_id}")
    else:
        print("✅ Best Query: (none)")
    print(f"✅ Average Overlap Ratio: {round(avg_overlap, 3)}")

    if debug_linkedin_enabled():
        print("\n[debug] Priority anchor:")
        print(f"  enabled={int(plan_trace.get('priority_anchor_enabled', 0))}")
        print(f"  query_id={plan_trace.get('priority_anchor_query_id', '')}")
        print(f"  ran={plan_trace.get('priority_anchor_ran', 0)}")
        print(f"  source={plan_trace.get('priority_anchor_source', '')}")
        skip_reason = plan_trace.get("priority_anchor_skip_reason") or ""
        if skip_reason:
            print(f"  skip_reason={skip_reason}")
        print(f"  unique_v2_new={anchor_v2_new}")
        if best:
            print(
                f"  best_run_new_v2={best.unique_v2_new} group={best.query_group}"
            )
    print()

    return all_jobs
