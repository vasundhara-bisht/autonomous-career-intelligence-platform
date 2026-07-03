# Product Status Summary

## Current product state

Temporal snapshot of product posture, shipped capabilities, limitations, and pointers to canonical docs. Update when milestones, scheduler posture, or the active roadmap phase changes.

**Last aligned with codebase:** 2026-07-03 — Promotion 4: lifecycle monitor, outreach, operational controls, AI refresh, TD10 listing_status.

**Documentation index:** [README.md §Documentation](../README.md#documentation) (primary entry point).

### Related documentation

| Document | Role |
|----------|------|
| **PRODUCT_STATUS_SUMMARY.md** | Current product state (temporal snapshot) — this document |
| [REPOSITORY_MAP.md](./REPOSITORY_MAP.md) | Code navigation, subsystem map, data flow |
| [PRODUCTION_OPERATIONS.md](./PRODUCTION_OPERATIONS.md) | Canonical daily and reset operator procedures |
| [SCHEDULER_SETUP.md](./SCHEDULER_SETUP.md) | Canonical launchd install, schedule, logs, uninstall |
| [PROJECT_COMMAND_REFERENCE.md](./PROJECT_COMMAND_REFERENCE.md) §10b | Commands, flags, troubleshooting |
| [SQLITE_IMPLEMENTATION_PLAN.md](./SQLITE_IMPLEMENTATION_PLAN.md) | Migration history and rollback reference |
| [SQLITE_PRODUCT_MEMORY_ARCHITECTURE.md](./SQLITE_PRODUCT_MEMORY_ARCHITECTURE.md) | Data model and design depth |
| [PUBLIC_REPO.md](./PUBLIC_REPO.md) | Publishing a sanitized mirror |

---

## 1. Current product state

**Career Intelligence Platform** is a personal, single-operator job search product: multi-channel acquisition, layered filtering, AI-assisted fit scoring with explainable reasons, recruiter relationship management, and a Streamlit decision dashboard.

**Codebase navigation:** [REPOSITORY_MAP.md](./REPOSITORY_MAP.md)

**Migration status:** D0–D8B complete. SQLite (`data/ai_job_agent.db`) is the **default operational source of truth**. Production-ready for daily personal use after bootstrap reset and validation ([PRODUCTION_OPERATIONS.md](./PRODUCTION_OPERATIONS.md) §2).

### At-a-glance platform status

| Dimension | Status | Detail |
|-----------|--------|--------|
| SQLite SOT (D8B) | Complete | §2A migration milestones |
| Production scheduler (Phase 2.95) | Complete | [SCHEDULER_SETUP.md](./SCHEDULER_SETUP.md) — acquisition 09:00/21:00 IST |
| Lifecycle Monitor / Scheduler B (Tasks 1–4 + OHM) | Complete | `src/monitor/`, `lifecycle_monitor_runs`, OHM governance; TD10 cutover complete |
| Repository map (Phase 2.97) | Complete | [REPOSITORY_MAP.md](./REPOSITORY_MAP.md) |
| Active build focus | Phase 3 / ops | 3A.2 + 3B + Outreach shipped; **Lifecycle Monitor Tasks 1–4 + OHM complete** |
| Prioritization engine (3A / 3A.2) | Complete | Four-queue waterfall Command Center on `dashboard_df` |
| HM recruiter enrichment (3B) | Complete | Job Listings HM edit → recruiters + append-only links |
| Recruiter relationship queues (3B+) | Not started | Dormant/warm/health action queues — deferred |

### Capability maturity

| Product area | Maturity | Roadmap | Notes |
|--------------|----------|---------|-------|
| Multi-source acquisition (5 sources) | Production Ready | Phase 1 | LinkedIn, Instahyre, Greenhouse, Lever, WeWorkRemotely |
| Instahyre Interested sync | Production Ready | Phase 2.57 | List-only Applied-state sync; early SQLite persist; `not_required` evals |
| User-managed pipeline routing | Production Ready | Phase 2.6+ | `pipeline_stages.py`; CRM stages skip AI (`not_required`) |
| LinkedIn query orchestration | Partial | Phase 2.57 | Core orchestration shipped; pagination/hydration gaps |
| Stage-1 filtering and deduplication | Production Ready | Phase 1 | V2 identity, fuzzy dedup |
| AI fit scoring | Production Ready | Phase 2, 2.59 | Batch OpenAI scoring + external profile |
| SQLite product memory | Production Ready | Phase 2.55 | D8B default-on write-primary |
| Historical memory and incremental routing | Production Ready | Phase 2.6 | Mostly complete; minor CSV export gaps |
| Streamlit dashboard | Production Ready | Phase 2.7 | Job Listings table, sidebar filters, `dashboard_df` / `filtered_df` split |
| Job Search Progression | Production Ready | Phase 2.7C | Discovery / Application / Outcomes snapshot cards (`funnel_workflow.py`) |
| Recruiter CRM | Production Ready | Phase 2.8 | v1 — discovery, stages |
| Dashboard analytics (v1) | Production Ready | Phase 2.7C | Pipeline analytics expander — counts, source rates (separate from progression UI) |
| Advanced historical analytics | Partial | Phase 5 | Trends, patterns, deferred SQL views |
| Production scheduler and parity gate | Production Ready | Phase 2.95, 2.56 | launchd acquisition 09:00/21:00 IST; lifecycle monitor **17:00 IST once daily**; `.env` required |
| Lifecycle Monitor (Scheduler B) | Production Ready | Tasks 1–4 + OHM | `listing_status` sole availability model; governance/operator controls |
| Job-centric Recommended Actions (3A / 3A.2) | Production Ready | Phase 3A | High Confidence / Apply Today / Apply This Week / Needs Review; waterfall assignment, 2×2 grid, per-queue display caps (8/10/12/10), dynamic panel height (max 360px), help icons, footer row, Open Job, Applied ✓ (three apply queues), Why? popovers; `dashboard_df` cohort |
| Hiring Manager recruiter enrichment (3B) | Production Ready | Phase 3B | HM edit in Job Listings; `recruiter_enrichment.py`; append-only `recruiter_job_links`; requires `SQLITE_DASHBOARD_WRITE` |
| LinkedIn HM extraction (flagship3 fallback) | Production Ready | Phase 1 / ops | Primary BEM + poster-section fallback in `scraper/linkedin.py`; probe via `scripts/probe_linkedin_hiring_manager.py` |
| LinkedIn HM data integrity (Tasks C–E) | Production Ready | Ops | Task C: manifest backfill (no-link cohort); Task D: dual-write sentinel merge; Task E: overwrite repair (link cohort); see [PROJECT_COMMAND_REFERENCE.md §8](./PROJECT_COMMAND_REFERENCE.md) |
| Posted date data layer (`posted_at_date`) | Production Ready | Phase A | Runtime derive + dual-write COALESCE; anchor + Playwright backfill scripts; **dashboard Posted column still uses `last_seen`** |
| Job listing availability | Production Ready | Task 4 (TD10) | `listing_status` only; inactive sweep retired |
| AI Refresh Health (dashboard) | Production Ready | Ops | Manual re-score run KPIs + history (`ai_refresh_ui.py`) |
| Operational Controls (dashboard) | Production Ready | Ops | Scheduler pause/resume + Refresh AI Evaluations trigger |
| LinkedIn Applied auto-promotion | Production Ready | 2.96 | Monitor detects user-applied; promotes to Applied + `monitor_exempt`; see PRODUCT_STATUS_SUMMARY.md |
| Outreach Intelligence V1.1 | Production Ready | Phase 3D | Hiring signal capture on `outreach_attempts` |
| Outreach Intelligence V1.2 (3D.2) | Production Ready | Phase 3D | LinkedIn post Fetch Details + AI prefill in Add Outreach |
| Outreach Intelligence V1.3 (3D.3) | Production Ready | Phase 3D | Job Outreach split; DB-driven prefill; `outreach_type` + `job_listing` signal type |
| Recruiter relationship action queues (3B+) | Not Started | Phase 3B+ | Dormant/warm/health queues — deferred |
| Advanced prioritization (3C+) | Not Started | Phase 3 | Signal weighting, ML — future |
| Net-new source expansion | Partial | Phase 6 | Wellfound/YC not started; RemoteOK deferred |
| Human-in-the-loop conversion (resume, outreach) | Future | Phase 7 | Not implemented |
| Application execution automation | Future | Phase 14 | 14A → 14B → 14C ladder |
| External integrations (Calendar, Gmail, MCP) | Future | Phase 13 | Not implemented |
| Autonomous career copilot | Future | Phase 11 | Not implemented |
| Local single-operator platform | Production Ready | Current platform | Daily production use supported |
| Cloud / SaaS / multi-user platform | Future | Phase 12 | Not implemented |

Maturity labels: **Production Ready** = shipped for daily operator use; **Partial** = started with meaningful gaps; **Future** = planned, not started; **Not Started** = active focus area with no implementation yet.

Phase evidence: PRODUCT_STATUS_SUMMARY.md.

---

## 2. Milestones shipped

### 2A — SQLite migration (D0–D8B)

| Phase | Deliverable | Status |
|-------|-------------|--------|
| **D0** | Read views (`historical_jobs_view`, `current_jobs_view`, etc.) | Complete |
| **D1** | Dashboard SQLite read path + CSV fallback | Complete |
| **D2** | DB-backed `jobs.csv` export from `current_jobs_view` | Complete |
| **D2.1** | Query/feed metadata in views and export | Complete |
| **D3** | Metadata hard parity (opt-in); Checkpoint H multi-run validation | Complete |
| **D4** | Pipeline reads historical index + descriptions from SQLite | Complete |
| **D5** | Write-primary: SQLite authoritative; CSV gated by `SQLITE_EXPORT_*` | Complete |
| **D6** | Dashboard + CRM writes to SQLite (`user_job_state`, recruiters) | Complete |
| **D7** | Reset profiles truncate SQLite; `export_csv_memory.py`; SOT validator mode | Complete |
| **D8A** | Promotion evidence (recovery drill, cap run, rollback) | Complete — [readiness report]() |
| **D8B** | Default-on SQLite flags; formal SOT promotion | Complete — sign-off |
| **Post-D8B** | `sqlite_flag()` unified gates; profile v2 file | Complete — [remediation report](../logs/d8b-remediation-report-20260603.md) |

Alembic head: `014_drop_currently_active` (run `alembic upgrade head` after pull).

### 2B — Platform capabilities (post-D8B)

| Capability | Roadmap phase | Status |
|------------|---------------|--------|
| Parity and validation framework | 2.56 | Complete |
| LinkedIn multi-query orchestration | 2.57 | Mostly complete |
| Identity V2 (JOB_KEY_V2) | 2.58 | Mostly complete |
| AI candidate profile v2 (external file) | 2.59 | Complete |
| Production scheduler (launchd + file lock + parity) | 2.95 | Complete — acquisition 09:00/21:00 IST |
| Lifecycle Monitor / Scheduler B (Tasks 1–4 + OHM) | 2.96 | Complete — monitor **17:00 IST once daily**; TD10 cutover complete |
| Repository map and doc governance | 2.97 | Mostly complete |
| Posted date data layer (Phase A) | Phase A | Complete — derive + backfills; dashboard display deferred |
| Job inactivity sweep (Phase B) | Phase B | **Retired** (Task 4) — replaced by `listing_status` lifecycle monitor |
| Outreach Intelligence V1.2 / V1.3 | Phase 3D | Complete — ingestion + Job Outreach split |
| LinkedIn HM integrity (Tasks B–E) | Ops | Complete — extract, backfill, forward protection, repair |

---

## 3. System at a glance

```text
Scrapers (LinkedIn, Instahyre feeds, Greenhouse, Lever, WeWorkRemotely)
    → [Instahyre] Interested sync → early SQLite persist (not in main all_jobs path)
    → main.py pipeline (normalize → incremental routing → cohort-specific paths → merge)
    → SQLite dual-write (product memory)
    → Views (historical_jobs_view, current_jobs_view, active_recruiters_view, …)
    → Streamlit dashboard: dashboard_df (viz/KPIs) + filtered_df (sidebar → table)
    → Optional CSV export (backup / handoff)

Scheduled (launchd): acquisition 09:00/21:00 IST; lifecycle monitor **17:00 IST once daily** → listing_status updates
Dashboard: ./scripts/run_dashboard.sh (listing-status visibility always on)
```

**Incremental routing** (after normalize, before Stage-1 for brand-new jobs):

- **Brand new** → Stage-1 → dedup → descriptions → AI queue
- **Needs AI only** → joins AI queue directly (skips repeat Stage-1 / dedup / fetch)
- **User-managed historical** → fully_processed + `not_required` (CRM stages; skip AI)
- **Fully processed** → merged from historical memory without re-scoring

Visual: [diagrams/architecture-diagram.png](../diagrams/architecture-diagram.png)

Structure, modules, and data flow: [REPOSITORY_MAP.md](./REPOSITORY_MAP.md) §4–§5.  
Data model depth: [SQLITE_PRODUCT_MEMORY_ARCHITECTURE.md](./SQLITE_PRODUCT_MEMORY_ARCHITECTURE.md).

---

## 4. Source of truth (SQLite)

| Concern | Authority |
|---------|-----------|
| Job memory, AI evaluations, descriptions, CRM | `data/ai_job_agent.db` |
| Feature flags | `src/db/config.py` (`sqlite_flag()` at runtime) |
| `jobs.csv` / historical / CRM on disk | **Exports** when enabled; with D8B write-primary, mid-run CSV writes for historical/descriptions/CRM are **skipped** by default |
| LinkedIn / Instahyre sessions | `data/*.json` auth files (never in DB) |
| AI candidate identity for scoring | [`config/profiles/ai_candidate_profile.example.md`](../config/profiles/ai_candidate_profile.example.md) |

No `SQLITE_*` environment variables are required for normal operation.

---

## 5. Operator workflows (summary)

### Acquisition

1. **Sources (5):** LinkedIn (query catalog), Instahyre (feeds + Interested sync), Greenhouse, Lever, WeWorkRemotely — per-source caps via env (`*_MAX_RUNS`).
2. **Incremental routing:** Historical index from SQLite when `SQLITE_PIPELINE_READ` on (default); splits brand-new / needs-AI-only / user-managed / fully processed.
3. **Cheap gates:** Stage-1 title/location filter; deduplication (V2 identity, URL, fuzzy).
4. **Descriptions:** Cache in SQLite; fetch on miss; reuse on subsequent runs.
5. **AI queue:** Batched OpenAI scoring (`BATCH_SIZE` default 20) using external profile file.
6. **Persistence:** Dual-write cohort at end of run; `jobs.csv` export via D2 DB path when enabled.

Operator steps: [PRODUCTION_OPERATIONS.md](./PRODUCTION_OPERATIONS.md) §3.

### Dashboard and CRM

- **Reads (default on):** `historical_jobs_view` (primary table + Job Search Progression), `current_jobs_view` (Latest Acquisition KPI), `active_recruiters_view`, `latest_acquisition_run_view` via [`dashboard/loaders.py`](../dashboard/loaders.py) and [`dashboard/data_flow.py`](../dashboard/data_flow.py).
- **Cohort model:** `dashboard_df` (visibility-scoped metrics/viz) vs `filtered_df` (sidebar → Job Listings only).
- **Writes (default on):** Pipeline stage → `user_job_state`; recruiter stage → `recruiters`; Hiring Manager edit → `jobs.hiring_manager` + recruiter upsert + append-only `recruiter_job_links` (Phase 3B).
- **UI:** `./scripts/run_dashboard.sh` — loads `.env`; Job Search Progression, KPI row, Listing/Age columns; Acquisition Health + Operational Monitor Health (summary KPIs + run history tables); SQLite data source under D8B defaults.
- **Listing visibility (Task 4 / TD10):** `open` and `closed` visible in Job Listings (all stages); `removed` hidden; Recommended Actions `listing_status=open` only. Legacy `currently_active` inactive model retired.
- **Fallback:** CSV loaders when `SQLITE_READ=0` or read errors.

### AI candidate profile

| Item | Detail |
|------|--------|
| Canonical file | [`config/profiles/ai_candidate_profile.example.md`](../config/profiles/ai_candidate_profile.example.md) |
| Override | `AI_CANDIDATE_PROFILE_PATH` |
| Loaded by | `load_candidate_profile()` in [`src/agent/profile_loader.py`](../src/agent/profile_loader.py) |
| Used in | OpenAI batch scoring only (not Stage-1 filter) |
| Editing guide | [config/profiles/README.md](../config/profiles/README.md) |

---

## 6. Production operating model

| Activity | Pattern |
|----------|---------|
| Acquisition | Automated **09:00 and 21:00 IST** via launchd; [SCHEDULER_SETUP.md](./SCHEDULER_SETUP.md); wrapper sets `LINKEDIN_MAX_RUNS=3`, loads `.env` |
| Lifecycle monitor | Automated **17:00 IST once daily** via launchd; `run_scheduled_lifecycle_monitor.sh` → `--apply` + TD9 parity; logs `logs/scheduled/lifecycle-monitor-*.log` |
| Review | `./scripts/run_dashboard.sh` for ranked jobs + CRM (manual, not scheduled) |
| Validation | Production parity after each run; scheduled wrapper runs `validate_sqlite_parity.py --mode production --fail-on-error` automatically |
| Backup | `archive_state.sh` + `export_csv_memory.py --all` + SOT validator |
| Profile tuning | Edit markdown profile before scoring runs |
| Emergency | `SQLITE_ENABLED=0` for CSV-only acquisition and dashboard |

Procedures: [PRODUCTION_OPERATIONS.md](./PRODUCTION_OPERATIONS.md).  
Scheduler install and logs: [SCHEDULER_SETUP.md](./SCHEDULER_SETUP.md).  
Lifecycle Monitor Task 3: SCHEDULER_SETUP.md.

---

## 7. Known limitations

- **Single-user, single profile** — no multi-tenant or per-persona DB profiles yet.
- **Job-centric queues only (3A / 3A.2)** — High Confidence, Apply Today, Apply This Week, and Needs Review (waterfall); Follow Up and Apply With Contact deferred.
- **No relationship action queues** — dormant/warm recruiter health queues (3B+) not built.
- **HM enrichment requires SQLite writes** — `SQLITE_DASHBOARD_WRITE=0` does not persist Hiring Manager or CRM enrichment.
- **Applied ✓ requires SQLite writes** — `SQLITE_DASHBOARD_WRITE=0` disables Recommended Actions quick-apply.
- **Outreach/touchpoint fields are DB-only on recruiters** — legacy `outreach_sent`, `touchpoint_count`, etc. on `recruiters` are not shown in CRM UI; operator outreach logging uses **Outreach Intelligence V1–V1.3** (`outreach_attempts`) instead.
- **Outreach Intelligence writes** — `SQLITE_DASHBOARD_WRITE=0` disables add/edit; when `SQLITE_READ=1`, KPIs, filters, and the outreach table remain visible read-only. Section is empty when `SQLITE_READ=0` (no SQLite dashboard read).
- **Posted date not in dashboard UI** — `posted_at_date` is stored at acquisition; Job Listings Posted column still uses `last_seen` fallback.
- **HM repair is operator-driven** — historical sentinel HM rows are not auto-repaired on every acquisition run; use Task C/E scripts when needed ([PROJECT_COMMAND_REFERENCE.md §8](./PROJECT_COMMAND_REFERENCE.md)).
- **Scraper fragility** — third-party site changes can break acquisition paths.
- **OpenAI batching** — `BATCH_SIZE` controls jobs per API request (default 20).
- **Description truncation** — `AI_DESCRIPTION_MAX_CHARS=3000` in scorer prep; very long postings may lose tail content.
- **Advanced analytics deferred** — v1 dashboard metrics only; time-series and pattern intelligence in Phase 5.
- **SOT validator vs on-disk CSV** — `--mode source-of-truth` is for post-export backup checks; use `--mode production` after daily acquisition.
- **Importer non-destructive** — DB orphans not removed by CSV import alone; cleanup scripts available.
- **No hosted API** — local Python + Streamlit only.
- **Manual Streamlit QA** — promotion relied on unit tests; periodic manual smoke recommended.
- **macOS-only scheduling** — launchd requires machine awake and user logged in; LinkedIn 32h query cooldown limits marginal LinkedIn yield on the second daily run.
- **Scheduler failure alerting** — non-zero launchd exit or parity FAIL not yet notified (Phase 10).

---

## 8. What's next

### 8A — Roadmap priorities

**Active build focus:** Phase 3 — Prioritization Intelligence (relationship queues and 3C+ remain). **Lifecycle Monitor Tasks 1–4 + OHM complete** — see PRODUCT_STATUS_SUMMARY.md.

**Canonical prioritized backlog:** PRODUCT_STATUS_SUMMARY.md → [Recommended Next 5 Priorities](./PRODUCT_STATUS_SUMMARY.md#recommended-next-5-priorities). Edit priorities there only; other docs link to that section.

### 8B — First-time setup (if not yet done)

Before daily cadence: complete **pre-production bootstrap reset** per [PRODUCTION_OPERATIONS.md](./PRODUCTION_OPERATIONS.md) §2; install LaunchAgents per [SCHEDULER_SETUP.md](./SCHEDULER_SETUP.md) (acquisition **09:00 / 21:00 IST**, lifecycle monitor **17:00 IST once daily**); ensure repo `.env` has `OPENAI_API_KEY`.

---

## 9. Future roadmap themes

**Canonical planning doc:** PRODUCT_STATUS_SUMMARY.md. The table below is a **short theme index only** — do not treat it as a second roadmap.

| Theme | Direction |
|-------|-----------|
| **Prioritization** | Action queues, signal-weighted ranking (Phase 3) |
| **Lifecycle Monitor Task 4** | Complete — listing_status-only visibility; see PRODUCT_STATUS_SUMMARY.md |
| **Ranking** | Separate metadata enrichment from sort signals (posted date, freshness) |
| **Conversion automation** | Resume, cover letters, outreach assist, app prep — human submits (Phase 7) |
| **Application execution** | Assisted → semi-autonomous → fully autonomous apply (Phase 14) |
| **Integrations** | Calendar, Gmail, MCP, Slack, Notion (Phase 13) |
| **Salary** | Structured compensation parsing where sources expose it |
| **Pagination** | Deeper InstaHyre feed traversal |
| **Alerting** | Scheduler failure notifications (Phase 10); delivery via external channels (Phase 13) |
| **Multi-user** | Isolated profiles and historical stores |
| **Testing** | Contract tests for identity, dedup, Stage-1 invariants |
| **Postgres / cloud** | Cloud evolution (out of current scope) |
| **Cross-platform scheduling** | Linux cron / cloud runner equivalent to launchd wrappers |

Profile variants per target role can use additional files under `config/profiles/` with `AI_CANDIDATE_PROFILE_PATH`.
