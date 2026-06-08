# Repository Map

**File:** `docs/REPOSITORY_MAP.md` — structural navigation guide for the codebase.

**Last audited:** 2026-06-08 (public clone)

**Operational snapshot:** [PRODUCT_STATUS_SUMMARY.md](./PRODUCT_STATUS_SUMMARY.md)

---

**Documentation index:** Start at [README.md §Documentation](../README.md#documentation); use this map for code navigation, subsystem ownership, and data flow.

**If you are an AI agent:** Read [PRODUCT_STATUS_SUMMARY.md](./PRODUCT_STATUS_SUMMARY.md) for current posture, then this map for file ownership and data flow before editing pipeline, DB, scraper, or dashboard code.

---

## 1. Executive Summary

### What the product is

A **personal, local-first career intelligence platform**: multi-source job acquisition, layered filtering, AI-assisted fit scoring with explainable reasons, recruiter relationship memory, and a Streamlit decision dashboard. Single operator; not multi-tenant.

### Current maturity

- **SQLite product memory (D0–D8B):** COMPLETE — `data/ai_job_agent.db` is the default operational source of truth.
- **Production scheduler:** COMPLETE — optional macOS launchd at 07:00 / 19:00.
- **Active roadmap phase:** Prioritization Intelligence (no priority engine in codebase yet).
- **Unit tests:** 21 modules under `tests/`; contract/invariant coverage remains a roadmap priority.

### Architecture style

- **Local-first monolith:** Python pipeline + Streamlit UI; no hosted API.
- **Stage-based pipeline:** Single orchestrator in `src/agent/main.py` with memory-aware incremental routing before Stage-1, then filter → dedup → enrich → score → persist for brand-new jobs.
- **Read model:** SQL views (`current_jobs_view`, `historical_jobs_view`, `active_recruiters_view`) consumed by dashboard and exports.
- **Write model:** End-of-run dual-write cohort to SQLite; optional CSV export for backup/handoff.

### SQLite as source of truth

| Concern | Authority |
|---------|-----------|
| Job memory, AI evaluations, descriptions, CRM | `data/ai_job_agent.db` |
| Feature flags (D8B defaults) | [`src/db/config.py`](../src/db/config.py) — `sqlite_flag()` |
| CSV files under `data/` | Exports when enabled; not the daily read path under D8B write-primary |
| LinkedIn / Instahyre sessions | `data/*.json` auth files (never in DB) |
| AI candidate identity | [`config/profiles/ai_candidate_profile.example.md`](../config/profiles/ai_candidate_profile.example.md) |

No `SQLITE_*` environment variables are required for normal operation.

### Scheduler architecture

```text
launchd plist (07:00 / 19:00)
  → scripts/scheduling/run_scheduled_acquisition.sh
    → source .env (OPENAI_API_KEY required)
    → export LINKEDIN_MAX_RUNS=3
    → scripts/scheduling/with_file_lock.py (fcntl lock)
      → scripts/scheduling/_acquisition_locked_body.sh
        → python main.py
        → validate_sqlite_parity.py --mode production --fail-on-error
```

Install and configuration detail (plist labels, logs, uninstall): [SCHEDULER_SETUP.md](./SCHEDULER_SETUP.md).

### Agent architecture (today vs future)

**Today:** `src/agent/` is a **deterministic pipeline** — not an autonomous agent. Modules are stage-specific (normalize, filter, dedup, score, persist). OpenAI is used only for batch job-fit scoring.

**Future:** Prioritization, conversion automation, and autonomous application flows would likely add new packages under `src/` — locations TBD.

---

## 2. Top-Level Directory Map

| Folder / file | Purpose | Key files | Notes |
|---------------|---------|-----------|-------|
| [`main.py`](../main.py) | Public pipeline entry shim | `main.py` | `python main.py` → `agent.main` |
| [`src/agent/`](../src/agent/) | Core pipeline logic | `main.py`, `ai_batch_scorer.py`, `job_identity.py`, `historical_persistence.py` | Pipeline orchestrator |
| [`src/db/`](../src/db/) | SQLite product memory | `config.py`, `services/dual_write.py`, `models/schema.py`, `read/` | SQLAlchemy + Alembic |
| [`src/paths.py`](../src/paths.py) | Canonical path resolution | `paths.py` | DATA_DIR, DB, config, auth paths |
| [`scraper/`](../scraper/) | Source adapters + orchestrators | `linkedin.py`, `instahyre.py`, `linkedin_query_orchestrator.py`, `acquisition_gate.py` | Playwright + HTTP APIs |
| [`dashboard/`](../dashboard/) | Streamlit operator UI | `app.py`, `loaders.py` | Read/write via SQLite views |
| [`scripts/`](../scripts/) | Ops, validation, maintenance | `scheduling/`, `validate_sqlite_parity.py`, `reset_state.sh`, `export_csv_memory.py` | Bash + venv Python |
| [`config/`](../config/) | Non-secret runtime config | `linkedin_queries.json`, `instahyre_feeds.json`, `profiles/` | No API secrets |
| [`docs/`](../docs/) | Documentation | This file, ops guides, SQLite plans | Public clone doc set |
| [`tests/`](../tests/) | Unit tests | 21 `test_*.py` modules | `unittest discover` from repo root |
| [`alembic/`](../alembic/) | DB schema migrations | `versions/001`–`004`, `env.py` | Head: `004_active_recruiters_view` |
| [`diagrams/`](../diagrams/) | Architecture visuals | `architecture-diagram.png`, `pipeline_flow.png`, dashboard screenshots | See [§2.1 Diagram assets](#21-diagram-assets) |
| [`data/`](../data/) | Runtime state (gitignored) | `ai_job_agent.db`, auth JSON, CSV exports | Created at runtime |
| [`logs/`](../logs/) | Acquisition + debug logs (gitignored) | `scheduled/acquisition-*.log` | Scheduler output |
| [`archive/`](../archive/) | Reset snapshots (gitignored) | `reset-YYYYMMDD-HHMM/` | Created by `archive_state.sh` |
| [`.env`](../.env) | Local secrets (gitignored) | `OPENAI_API_KEY`, optional overrides | Required for scheduled runs |

### 2.1 Diagram assets

| Asset | Status | Used by | Source |
|-------|--------|---------|--------|
| `architecture-diagram.png` | **Current** | README §System Architecture | Eraser (manual export; source of truth) |
| `pipeline_flow.png` | **Current** | README §End-to-End Pipeline Flow | `_generate_pipeline_flow_excalidraw.py` |
| `pipeline_flow.excalidraw` | Source | Regenerate `pipeline_flow.png` | `_generate_pipeline_flow_excalidraw.py` |
| `dashboard-hero.png`, `dashboard-crm.png`, `dashboard-analytics.png` | **Current** | README Dashboard (hero/CRM; analytics available) | Manual / export |

---

## 3. Critical Entry Points

| Entry point | How to run | Delegates to |
|-------------|------------|--------------|
| Pipeline | `python main.py` | [`src/agent/main.py`](../src/agent/main.py) via [`main.py`](../main.py) shim |
| Dashboard | `streamlit run dashboard/app.py` | [`dashboard/app.py`](../dashboard/app.py) → [`dashboard/loaders.py`](../dashboard/loaders.py) |
| Scheduled acquisition | launchd 07:00 / 19:00 | [`run_scheduled_acquisition.sh`](../scripts/scheduling/run_scheduled_acquisition.sh) |
| Install scheduler | `./scripts/scheduling/install_launchagents.sh` | Plist templates in `scripts/scheduling/launchd/` |
| LinkedIn acquisition | Inside pipeline | `run_linkedin_acquisition_session()` in [`linkedin_query_orchestrator.py`](../scraper/linkedin_query_orchestrator.py) |
| Instahyre acquisition | Inside pipeline | `run_instahyre_feed_session()` in [`instahyre_feed_orchestrator.py`](../scraper/instahyre_feed_orchestrator.py) |
| DB migrations | `alembic upgrade head` | [`alembic/versions/`](../alembic/versions/) |
| Parity validation | Post-run (automatic) or manual | [`scripts/validate_sqlite_parity.py`](../scripts/validate_sqlite_parity.py) |
| DB init | First-time / recovery | [`scripts/db_init.py`](../scripts/db_init.py) |
| State reset | Operator maintenance | [`scripts/reset_state.sh`](../scripts/reset_state.sh) |

Command detail: [PROJECT_COMMAND_REFERENCE.md](./PROJECT_COMMAND_REFERENCE.md).

---

## 4. Core Product Systems

| System | Purpose | Key files | Depends on | Status |
|--------|---------|-----------|------------|--------|
| **Acquisition** | Multi-source job ingestion | `scraper/*`, orchestrators, `acquisition_gate.py` | Playwright, auth JSON, `config/*.json` | COMPLETE |
| **Normalization** | Unified job dict shape | `src/agent/normalizer.py` | — | COMPLETE |
| **Stage-1 filtering** | Cheap PM/location/seniority gate | `src/agent/filter_engine.py` | — | COMPLETE |
| **Identity (V2)** | Stable cross-source job keys | `src/agent/job_identity.py`, `src/db/read/historical_index.py` | Historical index | MOSTLY COMPLETE |
| **Deduplication** | URL + fuzzy dedup | `src/agent/dedup_engine.py` | `rapidfuzz` | COMPLETE |
| **Incremental routing** | Skip re-work for known jobs | `src/agent/main.py`, `historical_persistence.py` | SQLite pipeline read | MOSTLY COMPLETE |
| **Description enrichment** | Fetch + cache full JD text | `description_fetcher.py`, `job_description_persistence.py` | Playwright, SQLite | COMPLETE |
| **AI scoring** | Batch OpenAI fit evaluation | `ai_batch_scorer.py`, `profile_loader.py`, `config/profiles/` | OpenAI API, `.env` | COMPLETE |
| **Historical memory** | Cross-run job retention | `historical_persistence.py`, SQLite `jobs`, `job_observations` | Dual-write | MOSTLY COMPLETE |
| **SQLite product memory** | Authoritative persistence + views | `src/db/*`, Alembic migrations | SQLAlchemy | COMPLETE |
| **CRM** | Recruiter discovery + relationship fields | `recruiter_crm.py`, `recruiters` table, dashboard CRM UI | Dual-write | COMPLETE (v1) |
| **Dashboard** | Operator jobs + CRM UI | `dashboard/app.py`, `loaders.py`, `dashboard_write.py` | SQLite views | COMPLETE |
| **Analytics (v1)** | Pipeline counts, source rates, CRM counters | `dashboard/app.py` — **Pipeline analytics** expander | Dashboard reads | COMPLETE |
| **Scheduler** | Unattended acquisition + parity | `scripts/scheduling/*` | launchd, `.env` | COMPLETE |
| **Validation / parity** | Post-run DB health checks | `validate_sqlite_parity.py`, `parity_checks.py` | SQLite | COMPLETE |
| **Prioritization** | Action queues, signal-weighted ranking | *(not implemented)* | — | NOT STARTED |

---

## 5. Data Flow

### Primary pipeline flow

```text
Scrapers (LinkedIn, Instahyre, Greenhouse, Lever, WeWorkRemotely)
  → normalize (normalizer.py)
  → incremental routing (historical lookup in main.py)
  → brand-new: Stage-1 filter → deduplicate → description fetch on miss → AI batch score
  → needs-AI-only: join AI queue (skip Stage-1 / dedup / fetch)
  → fully-processed: materialize from historical memory (skip Stage-1 / dedup / fetch / AI)
  → historical merge (historical_persistence.py)
  → dual-write SQLite (dual_write.py)
  → optional jobs.csv export
  → dashboard reads via SQL views
  → Pipeline analytics counters in Streamlit
```

**Routing cohorts:**

- **Brand new** → Stage-1 → dedup → descriptions → AI queue
- **Needs AI only** → joins AI queue directly (historical row already passed prior pipeline)
- **Fully processed** → merged from historical memory without re-scoring

### Secondary flows

| Flow | Path |
|------|------|
| **Dashboard write-back** | User edits → `dashboard_write.py` → `user_job_state` / `recruiters` |
| **Scheduler post-run** | `_acquisition_locked_body.sh` → parity validation → exit code to launchd |
| **Reset / archive** | `archive_state.sh` → `reset_state.sh` → truncate DB + seed from templates |
| **CSV export / handoff** | `export_csv_memory.py` → `data/*.csv` |
| **CRM discovery** | Pipeline → `recruiter_crm.py` → dual-write recruiters + job links |

Visual: [diagrams/architecture-diagram.png](../diagrams/architecture-diagram.png), [diagrams/pipeline_flow.png](../diagrams/pipeline_flow.png).

Depth: [SQLITE_PRODUCT_MEMORY_ARCHITECTURE.md](./SQLITE_PRODUCT_MEMORY_ARCHITECTURE.md).

---

## 10. Documentation Map

| Document | Audience | Purpose |
|----------|----------|---------|
| [README.md](../README.md) | All | Primary documentation index and product narrative |
| [CLONE_SETUP.md](./CLONE_SETUP.md) | New operators | Fresh clone install and first run |
| [PRODUCT_STATUS_SUMMARY.md](./PRODUCT_STATUS_SUMMARY.md) | Onboarding, operator | Temporal status snapshot, capability maturity, limitations |
| **REPOSITORY_MAP.md** (this file) | Dev, agent, operator | Structure, ownership, navigation |
| [PRODUCTION_OPERATIONS.md](./PRODUCTION_OPERATIONS.md) | Operator | Daily runbook, pre-production reset |
| [PROJECT_COMMAND_REFERENCE.md](./PROJECT_COMMAND_REFERENCE.md) | Operator, dev | Commands, flags, troubleshooting |
| [SCHEDULER_SETUP.md](./SCHEDULER_SETUP.md) | Operator | Optional macOS launchd install, schedule, logs |
| [SQLITE_PRODUCT_MEMORY_ARCHITECTURE.md](./SQLITE_PRODUCT_MEMORY_ARCHITECTURE.md) | Architect, dev | Data model depth, memory philosophy |
| [SQLITE_IMPLEMENTATION_PLAN.md](./SQLITE_IMPLEMENTATION_PLAN.md) | Migration history | D0–D8B timeline, rollback reference |
| [PUBLIC_REPO.md](./PUBLIC_REPO.md) | Maintainer | Sanitized mirror checklist |
| [config/profiles/README.md](../config/profiles/README.md) | Operator | AI candidate profile editing |

---

*End of repository map. For daily operations see [PRODUCTION_OPERATIONS.md](./PRODUCTION_OPERATIONS.md). For commands see [PROJECT_COMMAND_REFERENCE.md](./PROJECT_COMMAND_REFERENCE.md).*
