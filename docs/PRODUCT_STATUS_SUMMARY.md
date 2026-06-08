# Product Status Summary

High-level snapshot for onboarding, roadmap reviews, and portfolio context. This document describes the **public clone**; live operator logs and promotion sign-off artifacts are not shipped in this repository.

**Last aligned with codebase:** 2026-06-08 — D8B SQLite SOT, scheduler (launchd), repository map, routing-aware pipeline, dashboard analytics v1.

**Documentation index:** [README.md §Documentation](../README.md#documentation) (primary entry point).

| Doc | Use when you need |
|-----|-------------------|
| [CLONE_SETUP.md](./CLONE_SETUP.md) | Fresh-machine install and first run |
| [REPOSITORY_MAP.md](./REPOSITORY_MAP.md) | Code navigation, subsystem map, data flow |
| [SCHEDULER_SETUP.md](./SCHEDULER_SETUP.md) | Optional macOS launchd install, schedule, logs |
| [PRODUCTION_OPERATIONS.md](./PRODUCTION_OPERATIONS.md) | Daily workflow + pre-production reset |
| [PROJECT_COMMAND_REFERENCE.md](./PROJECT_COMMAND_REFERENCE.md) §10b | Commands, flags, troubleshooting |
| [SQLITE_IMPLEMENTATION_PLAN.md](./SQLITE_IMPLEMENTATION_PLAN.md) | Migration history and rollback reference |
| [SQLITE_PRODUCT_MEMORY_ARCHITECTURE.md](./SQLITE_PRODUCT_MEMORY_ARCHITECTURE.md) | Data model and design depth |
| [PUBLIC_REPO.md](./PUBLIC_REPO.md) | Portfolio-safe publishing checklist |

---

## 1. Current product status

**Career Intelligence Platform** is a personal, single-operator job search product: multi-channel acquisition, layered filtering, AI-assisted fit scoring with explainable reasons, recruiter relationship management, and a Streamlit decision dashboard.

**Codebase navigation:** [REPOSITORY_MAP.md](./REPOSITORY_MAP.md)

**Migration status:** D0–D8B complete. SQLite (`data/ai_job_agent.db`) is the **default operational source of truth**. After clone setup, run a bootstrap reset and validation pass ([PRODUCTION_OPERATIONS.md](./PRODUCTION_OPERATIONS.md) §2) before relying on daily cadence.

### At-a-glance platform status

| Dimension | Status | Detail |
|-----------|--------|--------|
| SQLite SOT (D8B) | Complete | §2 migration milestones |
| Production scheduler | Complete | [SCHEDULER_SETUP.md](./SCHEDULER_SETUP.md) — optional macOS launchd |
| Repository map | Complete | [REPOSITORY_MAP.md](./REPOSITORY_MAP.md) |
| Prioritization engine | Not started | Phase 3 — no action queue in codebase yet |
| Dashboard analytics (v1) | Complete | Pipeline analytics expander in Streamlit |

### Capability maturity

| Product area | Maturity | Notes |
|--------------|----------|-------|
| Multi-source acquisition (5 sources) | Production Ready | LinkedIn, Instahyre, Greenhouse, Lever, WeWorkRemotely |
| LinkedIn query orchestration | Partial | Core orchestration shipped; pagination/hydration gaps |
| Stage-1 filtering and deduplication | Production Ready | V2 identity, fuzzy dedup |
| AI fit scoring | Production Ready | Batch OpenAI scoring + external profile |
| SQLite product memory | Production Ready | D8B default-on write-primary |
| Historical memory and incremental routing | Production Ready | Mostly complete; minor CSV export gaps |
| Streamlit dashboard | Production Ready | Jobs table, pipeline stages, filters |
| Recruiter CRM | Production Ready | v1 — discovery, stages, responsiveness score |
| Dashboard analytics (v1) | Production Ready | Pipeline analytics expander — counts, source rates, CRM counters |
| Advanced historical analytics | Partial | Trends, patterns, deferred SQL views |
| Production scheduler and parity gate | Production Ready | launchd 07:00/19:00; `.env` required for scheduled runs |
| Prioritization and action queues | Not Started | Next major build focus |
| Local single-operator platform | Production Ready | Daily use supported after clone setup |

Maturity labels: **Production Ready** = shipped for daily operator use; **Partial** = started with meaningful gaps; **Not Started** = planned focus with no implementation yet.

---

## 2. Major milestones completed (D0–D8B)

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
| **D8A** | Promotion evidence (recovery drill, cap run, rollback) | Complete |
| **D8B** | Default-on SQLite flags; formal SOT promotion | Complete |
| **Post-D8B** | `sqlite_flag()` unified gates; example profile in repo | Complete |

Alembic head: `004_active_recruiters_view`.

### Platform capabilities (post-D8B)

| Capability | Status |
|------------|--------|
| Parity and validation framework | Complete |
| LinkedIn multi-query orchestration | Mostly complete |
| Identity V2 (JOB_KEY_V2) | Mostly complete |
| AI candidate profile (external file) | Complete |
| Production scheduler (launchd + file lock + parity) | Complete |
| Repository map and doc governance | Complete |

---

## 3. Current architecture summary

```text
Scrapers (LinkedIn, Instahyre, Greenhouse, Lever, WeWorkRemotely)
    → main.py pipeline (normalize → incremental routing → cohort-specific paths → merge)
    → SQLite dual-write (product memory)
    → Views (current_jobs_view, historical_jobs_view, active_recruiters_view, …)
    → Streamlit dashboard (read/write when flags on)
    → Optional CSV export (backup / handoff)
```

**Incremental routing** (after normalize, before Stage-1 for brand-new jobs):

- **Brand new** → Stage-1 → dedup → descriptions → AI queue
- **Needs AI only** → joins AI queue directly (skips repeat Stage-1 / dedup / fetch)
- **Fully processed** → merged from historical memory without re-scoring

Visual: [diagrams/architecture-diagram.png](../diagrams/architecture-diagram.png)

Structure, modules, and data flow: [REPOSITORY_MAP.md](./REPOSITORY_MAP.md) §4–§5.  
Data model depth: [SQLITE_PRODUCT_MEMORY_ARCHITECTURE.md](./SQLITE_PRODUCT_MEMORY_ARCHITECTURE.md).

---

## 4. Current source of truth (SQLite)

| Concern | Authority |
|---------|-----------|
| Job memory, AI evaluations, descriptions, CRM | `data/ai_job_agent.db` |
| Feature flags | `src/db/config.py` (`sqlite_flag()` at runtime) |
| `jobs.csv` / historical / CRM on disk | **Exports** when enabled; with D8B write-primary, mid-run CSV writes for historical/descriptions/CRM are **skipped** by default |
| LinkedIn / Instahyre sessions | `data/*.json` auth files (never in DB) |
| AI candidate identity for scoring | [`config/profiles/ai_candidate_profile.example.md`](../config/profiles/ai_candidate_profile.example.md) (override via `AI_CANDIDATE_PROFILE_PATH`) |

No `SQLITE_*` environment variables are required for normal operation.

---

## 5. Current acquisition workflow

1. **Sources (5):** LinkedIn (query catalog), Instahyre (feeds), Greenhouse, Lever, WeWorkRemotely — per-source run caps via env (`*_MAX_RUNS`).
2. **Incremental routing:** Historical index from SQLite when `SQLITE_PIPELINE_READ` on (default); splits brand-new / needs-AI-only / fully processed.
3. **Cheap gates:** Stage-1 title/location filter; deduplication (V2 identity, URL, fuzzy).
4. **Descriptions:** Cache in SQLite; fetch on miss; reuse on subsequent runs.
5. **AI queue:** Batched OpenAI scoring (`BATCH_SIZE` default 15, `DEBUG_LIMIT` default 300) using external profile file.
6. **Persistence:** Dual-write cohort at end of run; `jobs.csv` export via D2 DB path when enabled.

Operator steps: [PRODUCTION_OPERATIONS.md](./PRODUCTION_OPERATIONS.md) §3.

---

## 6. Current dashboard / CRM workflow

- **Reads (default on):** `current_jobs_view`, `historical_jobs_view`, `active_recruiters_view` via [`dashboard/loaders.py`](../dashboard/loaders.py).
- **Writes (default on):** Pipeline stage → `user_job_state`; recruiter stage, outreach fields → `recruiters` table.
- **UI:** `streamlit run dashboard/app.py` — sidebar should indicate SQLite data source under D8B defaults; **Pipeline analytics** expander shows run counts, source rates, and CRM counters.
- **Fallback:** CSV loaders when `SQLITE_READ=0` or read errors.

---

## 7. AI candidate profile overview

| Item | Detail |
|------|--------|
| Default file (this repo) | [`config/profiles/ai_candidate_profile.example.md`](../config/profiles/ai_candidate_profile.example.md) |
| Override | `AI_CANDIDATE_PROFILE_PATH` |
| Loaded by | `load_candidate_profile()` in [`src/agent/profile_loader.py`](../src/agent/profile_loader.py) |
| Used in | OpenAI batch scoring only (not Stage-1 filter) |
| Scoring rules | Remain in [`src/agent/ai_batch_scorer.py`](../src/agent/ai_batch_scorer.py) prompt |

Editing guide: [config/profiles/README.md](../config/profiles/README.md).

---

## 8. Production operating model

| Activity | Pattern |
|----------|---------|
| Acquisition | Automated **07:00 and 19:00** via launchd (optional); install/logs: [SCHEDULER_SETUP.md](./SCHEDULER_SETUP.md); wrapper sets `LINKEDIN_MAX_RUNS=3`, loads `.env` |
| Review | Streamlit dashboard for ranked jobs + CRM (manual, not scheduled) |
| Validation | Production parity after each run; scheduled wrapper runs `validate_sqlite_parity.py --mode production --fail-on-error` automatically |
| Backup | `archive_state.sh` + `export_csv_memory.py --all` + SOT validator |
| Profile tuning | Edit markdown profile before scoring runs |
| Emergency | `SQLITE_ENABLED=0` for CSV-only acquisition and dashboard |

Details: [PRODUCTION_OPERATIONS.md](./PRODUCTION_OPERATIONS.md).

---

## 9. Known limitations

- **Single-user, single profile** — no multi-tenant or per-persona DB profiles yet.
- **No prioritization engine** — jobs ranked by AI score only; action queues not built yet.
- **Scraper fragility** — third-party site changes can break acquisition paths.
- **AI cost cap** — `DEBUG_LIMIT` bounds scored jobs per run; remainder persisted as `skipped_by_cap`.
- **Description truncation** — `AI_DESCRIPTION_MAX_CHARS=3000` in scorer prep; very long postings may lose tail content.
- **Advanced analytics deferred** — v1 dashboard metrics only; time-series and pattern intelligence planned.
- **SOT validator vs on-disk CSV** — `--mode source-of-truth` is for post-export backup checks; use `--mode production` after daily acquisition.
- **Importer non-destructive** — DB orphans not removed by CSV import alone; cleanup scripts available.
- **No hosted API** — local Python + Streamlit only.
- **Manual Streamlit QA** — periodic manual smoke recommended.
- **Public clone** — placeholder LinkedIn IDs in config; replace before live LinkedIn runs.
- **macOS-only scheduling** — launchd requires machine awake and user logged in; LinkedIn 32h query cooldown limits marginal LinkedIn yield on the second daily run.
- **Scheduler failure alerting** — non-zero launchd exit or parity FAIL not yet notified externally.

---

## 10. Immediate next roadmap items

1. Complete [CLONE_SETUP.md](./CLONE_SETUP.md) and **pre-production bootstrap reset** ([PRODUCTION_OPERATIONS.md](./PRODUCTION_OPERATIONS.md) §2).
2. Establish **daily cadence** (acquisition + dashboard + parity check); optional [SCHEDULER_SETUP.md](./SCHEDULER_SETUP.md) for macOS automation.
3. Tune [`ai_candidate_profile.example.md`](../config/profiles/ai_candidate_profile.example.md) (or your private profile via `AI_CANDIDATE_PROFILE_PATH`) based on scoring quality.
4. Optional **manual Streamlit** smoke after reset.

---

## 11. Future roadmap themes

Short theme index (not a second roadmap):

| Theme | Direction |
|-------|-----------|
| **Prioritization** | Action queues, signal-weighted ranking |
| **Ranking** | Separate metadata enrichment from sort signals (posted date, freshness) |
| **Conversion automation** | Resume, cover letters, outreach assist — human submits |
| **Application execution** | Assisted → semi-autonomous → fully autonomous apply |
| **Integrations** | Calendar, Gmail, MCP, Slack, Notion |
| **Salary** | Structured compensation parsing where sources expose it |
| **Pagination** | Deeper InstaHyre feed traversal |
| **Alerting** | Scheduler failure notifications; delivery via external channels |
| **Multi-user** | Isolated profiles and historical stores |
| **Testing** | Contract tests for identity, dedup, Stage-1 invariants |
| **Postgres / cloud** | Cloud evolution (out of current scope) |
| **Cross-platform scheduling** | Linux cron / cloud runner equivalent to launchd wrappers |

Profile variants per target role can use additional files under `config/profiles/` with `AI_CANDIDATE_PROFILE_PATH`.
