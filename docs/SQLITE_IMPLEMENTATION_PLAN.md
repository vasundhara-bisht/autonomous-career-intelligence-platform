# SQLite Implementation Plan

> **Migration complete (D8B, 2026-06-03).** For daily operations use [PRODUCTION_OPERATIONS.md](./PRODUCTION_OPERATIONS.md). For system status see [PRODUCT_STATUS_SUMMARY.md](./PRODUCT_STATUS_SUMMARY.md). This document is **design history + rollback reference**.

Execution-oriented companion to [SQLITE_PRODUCT_MEMORY_ARCHITECTURE.md](./SQLITE_PRODUCT_MEMORY_ARCHITECTURE.md).

**Related docs**

| Document | Role |
|---|---|
| [PRODUCT_STATUS_SUMMARY.md](./PRODUCT_STATUS_SUMMARY.md) | What shipped (D0–D8B), SOT posture, roadmap |
| [PRODUCTION_OPERATIONS.md](./PRODUCTION_OPERATIONS.md) | Pre-reset + daily workflow |
| [SQLITE_PRODUCT_MEMORY_ARCHITECTURE.md](./SQLITE_PRODUCT_MEMORY_ARCHITECTURE.md) | Product memory model, table design, invariants |
| [PROJECT_COMMAND_REFERENCE.md](./PROJECT_COMMAND_REFERENCE.md) | **Canonical** day-to-day commands including SQLite §10b |

---

## 1. SQLite Implementation Goals

### Primary goals

1. **Preserve stabilized lifecycle semantics** — All valid deduped/description-enriched jobs persist; AI cap limits scoring only.
2. **Establish SQLite as local product memory** — Without breaking CSV fallback during rollout.
3. **Enable safe incremental rollout** — Each phase can be validated and rolled back independently.
4. **Keep single-user local ergonomics** — One DB file, simple inspection, minimal ops overhead.
5. **Prepare for future Postgres** — Schema and access patterns should not assume SQLite-only forever.

### Non-goals (MVP)

- Multi-user accounts or cloud sync
- Postgres migration (out of scope for D0–D8B)
- Removing CSV export/recovery tooling (CSV remains backup/handoff path)
- Advanced recruiter deduplication
- Automated AI reevaluation queues
- Observation archival/compaction
- Postgres deployment

### Success criteria (summary)

The migration succeeds when:

- Multiple real acquisition runs show CSV/DB parity on persistence cohort counts and `ai_status`.
- Reset profiles clear the correct SQLite table groups.
- `SQLITE_ENABLED=0` restores CSV-only operation instantly.
- The persistence bug (cap truncating memory) cannot recur via DB design.

---

## 2. MVP Implementation Scope

### MVP tables (implement first)

| Table | Purpose |
|---|---|
| `jobs` | Canonical job identity (`JOB_KEY_V2` unique) |
| `job_observations` | Per-run/per-source job sightings |
| `job_descriptions` | Description cache |
| `ai_evaluations` | Score, reason, `ai_status`, model, timestamp |
| `user_job_state` | Applied, rejected, interview, offer, notes, pipeline_stage |
| `recruiters` | Canonical recruiter identity |
| `recruiter_job_links` | Recruiter ↔ job relationships |
| `acquisition_runs` | One row per `python main.py` execution |
| `acquisition_query_runs` | LinkedIn query / InstaHyre feed execution |
| `query_cooldown_state` | Current orchestration cooldown state |

### MVP views (implement after core tables)

| View | Replaces / supports |
|---|---|
| `current_jobs_view` | Operational shape of `jobs.csv` |
| `latest_ai_evaluations_view` | Latest valid scored evaluation per job |

Defer to post-MVP: `active_recruiters_view`, `run_summary_view`, `source_effectiveness_view`.

### Explicitly deferred (post-MVP)

| Item | Reason | Status (2026-06) |
|---|---|---|
| `recruiter_observations` | Start with `recruiters` + `recruiter_job_links`; add observation history later | Still deferred |
| `reset_events` | Nice audit trail; not required for first dual-write | Still deferred |
| Dashboard read from SQLite | Was CSV-first during rollout | **Done (D1/D8B)** |
| CSV as export-only | Was written + trusted until promotion | **Done (D8B write-primary)** |
| AI reevaluation automation | Manual/rescore rules documented in architecture; not built in MVP | Still deferred |
| Observation compaction | Keep all MVP observations; revisit at scale | Still deferred |

### CSV / files during MVP

| Artifact | MVP role |
|---|---|
| `historical_jobs.csv` | Written + import source for DB bootstrap |
| `jobs.csv` | Written + parity check vs `current_jobs_view` |
| `job_descriptions.csv` | Written + import/parity |
| `recruiter_crm.csv` | Written + import/parity |
| `job_state.csv` | Written; merge into `user_job_state` on import |
| `.linkedin_query_state.json` | Written; optional dual-write to `query_cooldown_state` in later dual-write step |
| `linkedin_auth.json` | **File-only** — never in DB |
| `instahyre_auth.json` | **File-only** — never in DB |

---

## 3. Recommended Implementation Order

**Status: all phases A–J complete (D8B, 2026-06-03).** Do not start new migration work from this sequence — use [PRODUCTION_OPERATIONS.md](./PRODUCTION_OPERATIONS.md) for operator steps.

Historical sequence (completed):

```text
Phase A  — Foundation (schema, paths, flags)                    ✓
Phase B  — Importer + validation                                ✓
Phase C–E — Dual-write (jobs, AI, CRM, state)                   ✓
Phase F  — Views + export parity (D2)                           ✓
Phase G  — Reset tooling integration (D7)                       ✓
Phase H  — Multi-run validation                                 ✓
Phase I  — Dashboard read switch (D1/D6)                        ✓
Phase J  — SQLite source of truth (D8B)                         ✓
```

Promotion status: D8B complete (2026-06). Operator-local validation logs are not shipped in the public clone.

---

## 4. SQLAlchemy + Alembic Stack Decisions

### Decisions

| Choice | Decision | Rationale |
|---|---|---|
| Database driver | SQLite via SQLAlchemy (`sqlite3` stdlib) | Built-in, local-first, zero server |
| ORM | **SQLAlchemy 2.x declarative models** | Relationships, views, future Postgres |
| Migrations | **Alembic** | Versioned schema; reproducible bootstrap |
| Raw `sqlite3` only | **No** (except tiny one-off debug scripts) | Duplicates migration logic |
| SQLModel | **No** (optional later) | Extra abstraction; not needed for MVP |
| Heavy ORM in `main.py` | **No** | Keep pipeline dict-based; persist via repositories |

### Access pattern

```text
Pipeline (main.py)  →  job dicts  →  persistence service  →  repository  →  SQLAlchemy session
```

- Acquisition/scraping code stays unchanged in shape.
- New `src/db/repositories/*` encapsulate inserts/upserts.
- Dual-write orchestrator calls CSV writers **and** repositories.

### Dependencies (to add when implementing)

Planned additions to `requirements.txt`:

- `sqlalchemy>=2.0`
- `alembic>=1.13`

---

## 5. Proposed Folder Structure

Align with existing layout: `src/agent/` for library code, `scripts/` for CLI operations.

```text
src/
  paths.py                          # add jobs_db() helper
  db/
    __init__.py
    config.py                       # SQLITE_ENABLED, paths, engine URL
    engine.py                       # create_engine, session factory
    bootstrap.py                    # init DB, run migrations check
    models/
      __init__.py
      base.py
      jobs.py
      observations.py
      descriptions.py
      evaluations.py
      recruiters.py
      runs.py
      user_state.py
    repositories/
      jobs_repo.py
      observations_repo.py
      descriptions_repo.py
      evaluations_repo.py
      recruiters_repo.py
      runs_repo.py
      user_state_repo.py
    services/
      dual_write.py                 # orchestrates CSV + DB writes
      import_csv.py                 # library logic for importer
      parity.py                     # validation helpers

  agent/
    persistence/                    # thin adapters called from main.py (later)
      __init__.py

alembic/
  alembic.ini
  env.py
  versions/
    001_mvp_schema.py

scripts/
  db_init.py                        # create DB + migrate to head
  import_csv_memory.py              # CSV → SQLite (dry-run supported)
  validate_sqlite_parity.py         # import + post-dual-write parity modes
  validate_sqlite_parity.py         # production (default), import, source-of-truth, csv-mirror-sync
  validate_dual_write_parity.py     # deprecated → csv-mirror-sync
  cleanup_sqlite_orphan_job.py      # targeted single-key DB orphan removal
  export_sqlite_to_csv.py           # DB → CSV (later promotion aid)
  reset_runtime.py                  # extend: truncate SQLite table groups

docs/
  SQLITE_PRODUCT_MEMORY_ARCHITECTURE.md
  SQLITE_IMPLEMENTATION_PLAN.md       # this document
```

---

## 6. DB Bootstrap / Init Strategy

### DB file location

| Setting | Default | Override |
|---|---|---|
| Path | `data/ai_job_agent.db` | `AI_JOB_AGENT_DB_PATH` (absolute or relative to repo) |
| Data directory | `data/` | `AI_JOB_AGENT_DATA_DIR` (existing) |

Recommended: default path = `DATA_DIR / "ai_job_agent.db"` via new `paths.jobs_db()`.

### Initialization commands

```bash
# After dependencies installed
python scripts/db_init.py
```

`db_init.py` should:

1. Ensure `data/` exists.
2. Create empty SQLite file if missing.
3. Run `alembic upgrade head`.
4. Print schema revision and table list.
5. **Not** auto-run on every `python main.py` (explicit init only).

### Pipeline startup behavior (when implemented)

| Condition | Behavior |
|---|---|
| `SQLITE_ENABLED=0` | No DB access required |
| `SQLITE_ENABLED=1`, DB missing | Fail fast with message: run `db_init` first |
| `SQLITE_ENABLED=1`, schema behind | Fail fast: run `alembic upgrade head` |

Silent auto-migrate on every pipeline run is **discouraged** — hides migration drift.

---

## 7. Alembic Migration Strategy

### Principles

1. **All schema changes go through Alembic revisions** — No ad-hoc `CREATE TABLE` in application code.
2. **One MVP revision first** — `001_mvp_schema.py` creates all MVP tables + core indexes.
3. **Small follow-up revisions** — Add views, indexes, or deferred tables in separate revisions.
4. **Views** — Prefer `op.execute()` for `CREATE VIEW` in migrations, or define in a dedicated revision `002_views.py`.

### Revision workflow (developer)

```bash
alembic revision -m "describe change"
alembic upgrade head
alembic downgrade -1   # only in dev, with backup
```

### Index priorities (MVP)

- Unique index on `jobs.job_key_v2`
- Index on `job_observations.job_id`, `job_observations.run_id`
- Index on `ai_evaluations.job_id`, `ai_evaluations.evaluated_at`
- Index on `recruiters.recruiter_key`
- Index on `recruiter_job_links.recruiter_id`, `recruiter_job_links.job_id`

### Postgres-forward notes (do not implement yet)

- Use portable types (`String`, `Integer`, `Float`, `Boolean`, `DateTime`, `Text`).
- Avoid SQLite-only assumptions in application logic.
- Use `JSON` type sparingly; prefer normalized columns for query state.

---

## 8. CSV Importer Plan

### Purpose

Populate SQLite from existing CSV memory **before** dual-write, without changing pipeline behavior.

### Import order (conflict resolution)

| Step | Source | Target | Authority rule |
|---|---|---|---|
| 1 | `historical_jobs.csv` | `jobs`, `user_job_state`, initial `ai_evaluations`, synthetic `job_observations` | **Primary** for job identity and scored history |
| 2 | `job_descriptions.csv` | `job_descriptions` | Match on `JOB_KEY_V2` |
| 3 | `recruiter_crm.csv` | `recruiters`, `recruiter_job_links` | Primary for CRM |
| 4 | `job_state.csv` | `user_job_state` | Merge; do not overwrite non-empty with empty |
| 5 | `jobs.csv` | Enrichment only | **Do not** override historical scored fields if conflict |
| 6 | `.linkedin_query_state.json` | `query_cooldown_state` | Operational seed |

### Importer features (planned)

```bash
python scripts/import_csv_memory.py --dry-run
python scripts/import_csv_memory.py
```

Importer is **non-destructive** (upsert only). To remove DB orphans not present in CSV, use `python scripts/cleanup_sqlite_orphan_job.py` (see [PROJECT_COMMAND_REFERENCE.md §10b](./PROJECT_COMMAND_REFERENCE.md#sqlite-product-memory-source-of-truth)).

Output: `data/IMPORT_APPLIED.json` (mirror `RESET_APPLIED.json` style) with row counts and warnings.

### Import validation (must pass before dual-write)

| Check | Expected |
|---|---|
| `COUNT(jobs)` | = `historical_jobs.csv` data rows |
| `COUNT(job_descriptions)` | = `job_descriptions.csv` rows |
| `COUNT(recruiters)` | = `recruiter_crm.csv` rows |
| Latest evaluation `scored` | Matches historical rows with score/reason |
| `JOB_KEY_V2` uniqueness | No duplicates |
| Unscored semantics | No `ai_score=0` unless `ai_status=scored` |

---

## 9. Dual-Write Rollout Plan

### Master switch

Dual-write only activates when **both**:

- `SQLITE_ENABLED=1`
- `SQLITE_DUAL_WRITE=1`

CSV writers always run in MVP (no flag to disable CSV during rollout).

### Incremental dual-write sequence (write-track phases)

> This table tracks **write-track rollout** only.  
> Dashboard/read/export phases are tracked separately in §13.

| Write-track step | What gets dual-written | CSV counterpart |
|---|---|---|
| W1 | `acquisition_runs`, `acquisition_query_runs` | Logs only (optional JSON still written) |
| W2 | `jobs`, `job_observations` (full persistence cohort) | `historical_jobs` upsert path + observation implied in historical refresh |
| W3 | `job_descriptions` | `job_descriptions.csv` |
| W4 | `ai_evaluations` (`scored`, `skipped_by_cap`, `pending`) | `jobs.csv` / historical score fields |
| W5 | `recruiters`, `recruiter_job_links` | `recruiter_crm.csv` |
| W6 | `user_job_state` | `historical_jobs` + `job_state.csv` |
| W7 | `query_cooldown_state` | `.linkedin_query_state.json` |
| W8 | Regenerate / compare `current_jobs_view` vs `jobs.csv` | `save_to_csv_via_db_export()` (D2; parity-gated) |

### Dual-write failure behavior

| Failure | Behavior |
|---|---|
| SQLite write fails | Log error; **CSV write must still succeed**; run marked degraded in `acquisition_runs` if possible |
| CSV write fails | Existing pipeline failure semantics (unchanged) |

SQLite must never block a successful CSV-only run during MVP.

---

## 10. Validation Tooling Plan

### Scripts (implemented/active)

| Script | When to run |
|---|---|
| `scripts/validate_sqlite_parity.py` | After import (`--mode import`); optional post-import (`--mode post-dual-write`) |
| `scripts/validate_sqlite_parity.py --mode production` | After each acquisition run (SQLite-first; default) |
| `scripts/validate_sqlite_parity.py --mode csv-mirror-sync` | Legacy strict CSV mirror parity (optional; deprecated dual-write script alias) |
| `scripts/validate_bootstrap.py` | Continue for CSV schema (unchanged during MVP) |
| `scripts/export_sqlite_to_csv.py` | Optional: generate CSV from DB for diff |
| `tests/test_d2_export.py` | D2 export parity gate unit tests (`python -m unittest tests.test_d2_export -q`) |

### Post-run parity report (minimum)

Validation script should print a single summary block:

```text
Persistence cohort (log):     114
jobs.csv rows:                114
DB current_jobs_view rows:    114
historical_jobs.csv rows:     114
job_descriptions.csv rows:    114
DB job_descriptions rows:     114
AI scored:                    114
ai_status scored (CSV):       114
ai_status scored (DB):        114
ai_status skipped_by_cap:     0
recruiter_crm.csv rows:       22
DB recruiters rows:           22
INVARIANT persistence >= scored: PASS
INVARIANT skipped does not blank scored: PASS (sampled)
```

### Sampling checks

For 5–10 known `JOB_KEY_V2` values, compare:

- title, company, source
- latest `ai_status`, `ai_score`, `reason`
- recruiter link if Instahyre

### Multi-run gate

Before promoting SQLite:

- **At least 3** real acquisition runs with dual-write enabled.
- All runs pass parity block.
- At least one run where `AI candidates > DEBUG_LIMIT` to exercise `skipped_by_cap` (when cap lowered for test).

---

## 11. Feature Flags and Rollback Strategy

### Environment variables (implemented)

| Variable | Default | Meaning |
|---|---|---|
| `SQLITE_ENABLED` | `1` (D8B) | Master: any SQLite access; **`0` = emergency CSV-only** |
| `SQLITE_DUAL_WRITE` | `1` (D8B) | Write to SQLite during pipeline |
| `SQLITE_READ` | `1` (D8B) | Dashboard reads from SQLite when `SQLITE_ENABLED=1` |
| `SQLITE_PIPELINE_READ` | `1` (D8B) | Pipeline reads historical index + descriptions from SQLite |
| `SQLITE_WRITE_PRIMARY` | `1` (D8B) | SQLite-first persistence; CSV gated by `SQLITE_EXPORT_*` |
| `SQLITE_DASHBOARD_WRITE` | `1` (D8B) | Dashboard writes to SQLite |
| `SQLITE_EXPORT_JOBS_CSV` | `1` (D8B) | Export `jobs.csv` from DB |
| `SQLITE_EXPORT_HISTORICAL_CSV` | `0` (D8B) | Optional historical CSV export |
| `SQLITE_EXPORT_DESCRIPTIONS_CSV` | `0` (D8B) | Optional descriptions CSV export |
| `SQLITE_EXPORT_CRM_CSV` | `0` (D8B) | Optional CRM CSV export |
| `SQLITE_EXPORT_FROM_DB` | `1` when `SQLITE_ENABLED=1` (D2) | Generate `jobs.csv` from `current_jobs_view`; legacy export on hard parity failure |
| `AI_JOB_AGENT_DB_PATH` | unset | Override DB file path |

Optional dev-only:

| Variable | Meaning |
|---|---|
| `SQLITE_FAIL_ON_ERROR` | `1` = raise on DB write failure; `0` = log and continue (default during rollout) |

### Rollback levels

| Level | Action | When |
|---|---|---|
| **L0 — Instant** | `SQLITE_ENABLED=0` | Any DB issue; revert to CSV-only immediately |
| **L1 — Disable dual-write** | `SQLITE_DUAL_WRITE=0` | DB read-only debugging; CSV authoritative |
| **L1b — Disable DB export only** | `SQLITE_EXPORT_FROM_DB=0` | Keep dual-write; `jobs.csv` from legacy in-memory export (D2 rollback) |
| **L2 — Re-import** | `import_csv_memory.py` (+ orphan cleanup if needed) | DB corrupted or drifted |
| **L3 — Delete DB** | Remove `ai_job_agent.db` + `db_init` + import | Clean slate |
| **L4 — Restore archive** | `./scripts/archive_state.sh` + reset + import | Catastrophic; same as today |

CSV files and `archive/reset-*` tarballs remain the **operational safety net** until promotion.

---

## 12. Reset Tooling Integration Plan

Extend existing profile-driven reset (`scripts/reset_runtime.py`) to truncate SQLite table groups when `SQLITE_ENABLED=1`.

### Profile → SQLite table truncation (MVP)

| Profile | Truncate (SQLite) | Preserve |
|---|---|---|
| `bootstrap` | All MVP product tables + `query_cooldown_state` | Auth files |
| `acquisition` | `acquisition_runs`, `acquisition_query_runs`, `query_cooldown_state`; optional session export tables | `jobs`, descriptions, evaluations, recruiters, user state |
| `crm-preserving` | Jobs domain tables + query state | `recruiters`, `recruiter_job_links` |
| `full` | All MVP tables (same as bootstrap) | Auth unless `--reset-auth` |

### Reset behavior rules

1. **Truncate tables, do not delete `.db` file** — Keeps Alembic revision history valid.
2. **Run CSV reset and SQLite reset in same profile** — Same user intent, both stores.
3. **Dry-run shows both** — CSV files + SQLite tables affected.
4. **`RESET_APPLIED.json` extended** — Include `sqlite_tables_truncated` list.

### Order of operations (reset)

```text
1. Archive (user responsibility, existing flow)
2. Confirm profile
3. Truncate SQLite tables (if SQLITE_ENABLED)
4. Reset CSV files (existing behavior)
5. Write RESET_APPLIED.json
```

---

## 13. Dashboard Migration Sequencing

### Status snapshot (as of 2026-06-02, D2 sign-off)

- **D0 (read foundation): COMPLETE**
  - SQLite read views + read-model layer implemented.
  - `shadow_read_parity.py --fail-on-error`: PASS.
- **D1 (dashboard read switch): COMPLETE**
  - Dashboard read routing implemented behind `SQLITE_READ`.
  - CSV fallback preserved for dashboard reads.
  - Manual Streamlit validation complete; no runtime KeyErrors.
  - `validate_dual_write_parity.py --fail-on-error`: PASS.
- **D2 (DB-backed export): COMPLETE** (formal sign-off 2026-06-02)
  - `save_to_csv_via_db_export()` in [`src/agent/main.py`](../src/agent/main.py); source [`load_current_jobs_export_source_df()`](../src/db/read/export_cohort.py) → `current_jobs_view`.
  - Pipeline order: `dual_write_runtime_snapshot()` then DB export (so latest run `job_observations` exist before read).
  - Hard parity on behavior-critical export columns; `rejected` bool/`0`/`1` normalization in `_d2_hard_parity_check()`.
  - Metadata (`linkedin_query_*`, `instahyre_*`) WARN-only; legacy `save_to_csv()` fallback on hard parity failure.
  - Sign-off run 8: cohort 206, terminal `jobs.csv export_mode=db_current_jobs_view`, no hard parity fallback; metadata WARN lines only.
  - Post-run `validate_dual_write_parity.py --fail-on-error`: PASS; `python -m unittest tests.test_d2_export -q`: PASS.
  - Checkpoint **H** (3+ consecutive clean DB-export runs): superseded by Plan A D3 sign-off below.
- **D2.1 (metadata restoration): COMPLETE** (2026-06-02)
  - Alembic `003_query_metadata`: `acquisition_query_runs.query_group`, `filter_profile`, `run_ts`; `current_jobs_view` joins `job_observations` → `acquisition_query_runs`.
  - Dual-write sets `job_observations.query_run_id` and populates extended query-run fields from job dicts.
  - Metadata remains **WARN-only** at export unless `SQLITE_METADATA_HARD_PARITY=1` (D3 opt-in).
  - Forward-only (no import backfill); optional `scripts/backfill_observation_query_runs.py` for prior runs.
  - Validation: migration at head; `python -m unittest tests.test_d2_export tests.test_db_read_views tests.test_dual_write_metadata -q` PASS; `validate_dual_write_parity.py --fail-on-error` PASS (D2 metadata section).
  - Runtime sign-off: run 9 + runs 11–13 (2026-06-03) — zero export metadata WARNs; metadata populated in `jobs.csv` via DB export.
- **D3 / Plan A (Checkpoint H): COMPLETE** (2026-06-03)
  - **3/3 consecutive clean DB-export runs:** acquisition runs **11, 12, 13** (run 10 failed — Playwright missing in agent env; legacy export fallback; does not count).
  - Each pass run: `jobs.csv export_mode=db_current_jobs_view`, dual-write `success=1`, zero export-time metadata WARNs, `validate_dual_write_parity.py --fail-on-error` PASS (including D2 METADATA PARITY).
  - Evidence logs: operator-local log (run 11), operator-local log (run 12), operator-local log (run 13), operator-local log (run 14 hard-parity trial).
  - Optional: `SQLITE_METADATA_HARD_PARITY=1` trial run 14 — DB export PASS (no hard parity fallback).
  - Optional: `scripts/backfill_observation_query_runs.py --dry-run` on run 13 — `updated=0 skipped=36` (forward-only cohort already linked).
  - `SQLITE_METADATA_HARD_PARITY=1` remains opt-in (default WARN-only).

### Phase D0 — No change (MVP dual-write) ✅ COMPLETE

- Dashboard continues reading `jobs.csv` and `historical_jobs.csv`.
- Optional dev-only banner: "SQLite parity: PASS/FAIL" from last validation.

### Phase D1 — Read switch (promotion sub-phase) ✅ COMPLETE

Implementation: [`dashboard/loaders.py`](../dashboard/loaders.py) + `SQLITE_READ` in [`dashboard/app.py`](../dashboard/app.py).

Implemented behavior:
1. Added `SQLITE_READ=1` path in `dashboard/app.py` (via `dashboard/loaders.py`).
2. Loads `current_jobs_view` (jobs.csv key-aligned) and `historical_jobs_view` for display reads.
3. Keeps CSV load as fallback if `SQLITE_READ=0` or DB missing.
4. Preserves `ai_status` semantics: pending/skipped not shown as score 0.

### Phase D2 — CSV export from DB ✅ COMPLETE

Implemented (signed off 2026-06-02):

1. `SQLITE_EXPORT_FROM_DB=1` (default when `SQLITE_ENABLED=1`) routes export through `save_to_csv_via_db_export()`.
2. `jobs.csv` written from `current_jobs_view` after dual-write when hard parity passes (`jobs.csv export_mode=db_current_jobs_view`).
3. Hard parity compares legacy in-memory cohort vs DB view on identity, AI, location, sort/priority, and `rejected` (with boolean normalization).
4. Legacy in-memory `save_to_csv()` remains fallback on hard parity failure or DB read errors.
5. Dashboard continues supporting both CSV (`SQLITE_READ=0`) and SQLite display reads (`SQLITE_READ=1`).

D2 scope exclusions (deferred, not blockers for D2 sign-off):

- Query/feed metadata parity (`linkedin_query_*`, `linkedin_run_ts`, `instahyre_*`) is **WARN-only** at export time (D2.1); hard-fail via `SQLITE_METADATA_HARD_PARITY=1` (D3 opt-in).

### Phase D2.1 — Metadata restoration ✅ COMPLETE

1. Migration `003_query_metadata` extends `acquisition_query_runs` and recreates `current_jobs_view` with metadata joins.
2. [`dual_write.py`](../src/db/services/dual_write.py) links `job_observations.query_run_id` to query runs keyed by `(source, query_id)`.
3. DB export restores metadata in `jobs.csv` when view matches legacy (WARN-only parity by default).

### Phase D3 / Plan A — Checkpoint H ✅ COMPLETE

Operational hardening (2026-06-03); no code changes.

1. Three consecutive clean dual-write acquisition runs with DB export and full parity PASS (runs 11–13).
2. Post-run validator ritual documented in [`PROJECT_COMMAND_REFERENCE.md`](PROJECT_COMMAND_REFERENCE.md) §10b.
3. Optional metadata hard parity trial (run 14) and backfill dry-run completed.

**Next:** Plan B (D4 pipeline read switch) — see `.cursor/plans/plan_b_d4_pipeline_read.plan.md`.

### Phase D4 / Plan B — Pipeline read switch ✅ COMPLETE

Pipeline reads product memory from SQLite when `SQLITE_PIPELINE_READ=1`; CSV writes unchanged (dual-write parity preserved).

1. **`SQLITE_PIPELINE_READ`** — `load_historical_index()` and `load_description_store()` read from `historical_jobs_view` and `job_descriptions` via [`src/db/read/historical_index.py`](../src/db/read/historical_index.py) and [`src/db/read/description_store.py`](../src/db/read/description_store.py); CSV fallback on error or flag off.
2. **`SQLITE_QUERY_STATE_READ`** (opt-in) — LinkedIn orchestrator reads `query_cooldown_state`; `.linkedin_query_state.json` remains write-through mirror.
3. Unit tests: `tests/test_pipeline_read.py` (index shape, description hydrate, query state, routing fixture).
4. Runtime flag evaluation in `db/read/engine.py` (env read at call time, not import time).

**Validation:** acquisition run 15 (2026-06-02) with `SQLITE_ENABLED=1 SQLITE_DUAL_WRITE=1 SQLITE_PIPELINE_READ=1`; terminal confirmed `Pipeline historical index: SQLite`, `Pipeline description store: SQLite`, routing split 140/0/532, dual-write `success=1`; `validate_dual_write_parity.py --fail-on-error` OVERALL PASS.

**Next:** Plan C (D5 write-primary switch) — see `.cursor/plans/plan_c_d5_write_primary.plan.md`.

### Phase D5 / Plan C — SQLite write primary ✅ COMPLETE

When `SQLITE_WRITE_PRIMARY=1`, dual-write is the authoritative persistence path; CSV writes are optional exports gated by `SQLITE_EXPORT_*` flags.

1. **`SQLITE_WRITE_PRIMARY`** — skips `update_historical_jobs` CSV write, mid-run `flush_description_store`, and CRM CSV mutation; dual-write upserts remain authoritative.
2. **`SQLITE_EXPORT_*_CSV`** — post dual-write exports from [`src/db/write/csv_export.py`](../src/db/write/csv_export.py): `historical_jobs_view`, `job_descriptions`, `recruiters`.
3. **`SQLITE_EXPORT_JOBS_CSV`** — gates D2 `jobs.csv` export (default on; falls back to `SQLITE_EXPORT_FROM_DB` when unset).
4. Pipeline order: dual-write → optional CSV exports → jobs export → CRM summary (write-primary) or CSV CRM (legacy).
5. Unit tests: `tests/test_write_primary.py`.

**Validation:** acquisition run 16 (2026-06-02) with `SQLITE_WRITE_PRIMARY=1` and all exports enabled; terminal confirmed DB exports (394/377/153 rows), dual-write `success=1`; `validate_dual_write_parity.py --fail-on-error` OVERALL PASS.

**Next:** Plan D (D6 dashboard CRM/historical write) — see `.cursor/plans/plan_d_d6_dashboard_crm.plan.md`.

### Phase D6 / Plan D — Dashboard + CRM SQLite ✅ COMPLETE

Dashboard reads CRM via `active_recruiters_view` and writes user/recruiter state to SQLite when `SQLITE_DASHBOARD_WRITE=1`.

1. Migration `004_active_recruiters_view` — CRM dashboard shape with link-based `jobs_connected` (full operational cohort).
2. [`dashboard/loaders.py`](../dashboard/loaders.py) — `load_recruiter_crm_df()` with CSV fallback.
3. [`src/db/services/dashboard_write.py`](../src/db/services/dashboard_write.py) — `user_job_state` + recruiter stage upserts.
4. [`dashboard/app.py`](../dashboard/app.py) — DB read/write when flags on; CSV path preserved for rollback.
5. [`scripts/export_csv_memory.py`](../scripts/export_csv_memory.py) — stub for historical/CRM/description handoff (Plan E expands).
6. Unit tests: `tests/test_dashboard_loaders.py` (CRM loader + write round-trip).

**Validation:** migration 004 applied; `active_recruiters_view` returns 153 recruiters / 179 links on production DB; unit tests PASS. Manual Streamlit review with `SQLITE_DASHBOARD_WRITE=1` recommended before production use.

**Next:** Plan E (D7 reset + full export) — see `.cursor/plans/plan_e_d7_reset_recovery.plan.md`.

### Phase D7 / Plan E — Reset, recovery, and validator inversion ✅ COMPLETE

1. [`src/db/reset_sqlite.py`](../src/db/reset_sqlite.py) — profile-scoped SQLite `DELETE` (truncate tables, keep `.db` + Alembic head).
2. [`scripts/reset_runtime.py`](../scripts/reset_runtime.py) — `sqlite_tables_truncated` in `RESET_APPLIED.json`; gated on `SQLITE_ENABLED=1`.
3. [`scripts/export_csv_memory.py`](../scripts/export_csv_memory.py) — full export (`--all`, per-artifact flags, `--output-dir`, `--dry-run`).
4. [`scripts/validate_sqlite_parity.py`](../scripts/validate_sqlite_parity.py) — `--mode source-of-truth` (DB reference, CSV export compare).
5. `job_state.csv` removed from reset profiles; import warns when legacy file present.
6. Unit tests: `tests/test_reset_sqlite.py`.

**Validation:** bootstrap truncate on temp DB (all product tables empty); `export_csv_memory.py --dry-run --all` + `--mode source-of-truth --fail-on-error` PASS on production DB; `reset_runtime.py --profile bootstrap --dry-run` shows SQLite table list + row counts; acquisition profile preserves `jobs` row in unit test; SOT FAIL on intentional CSV drift (unit test).

**Next:** Plan F (D8 promotion) superseded by D8A + D8B (completed in private production; evidence retained operator-local).

### Phase D8A — Promotion evidence validation ✅ COMPLETE

Evidence-only phase; no default flag changes. Verdict: `READY_FOR_D8B`.

- Readiness, cap drill (`DEBUG_LIMIT=2`, 66 `skipped_by_cap`), live recovery (archive → bootstrap → import PASS), `SQLITE_ENABLED=0` rollback, and opt-in promotion-stack runs — validated on operator hardware (logs not in this repo).

### Phase D8B — Source-of-truth promotion ✅ COMPLETE

1. [`src/db/config.py`](../src/db/config.py) — defaults flipped: `SQLITE_ENABLED`, `DUAL_WRITE`, `PIPELINE_READ`, `WRITE_PRIMARY`, `READ`, `DASHBOARD_WRITE` → `True`; export historical/descriptions/CRM → `False`; jobs export → `True`.
2. Documentation posture updated (§10b, README, §16).
3. Post-flip smoke (no env overrides): acquisition + SOT validator PASS.
4. Post-remediation: `sqlite_flag()` unified runtime gates; smoke re-run PASS.

**Next:** Optional CI wiring; Postgres migration (out of scope).

### Phase D3 — Metadata hardening (opt-in, ongoing)

- `SQLITE_METADATA_HARD_PARITY=1` promotes metadata coverage gaps to hard export parity failure (trial run 14 PASS).
- `scripts/backfill_observation_query_runs.py` — best-effort `query_run_id` repair for prior runs.

### Dashboard validation checklist

| Check | Expected |
|---|---|
| Row count | Matches last run persistence cohort |
| Scored jobs | Show score badges |
| Skipped/pending | "Pending AI" label, not red/zero |
| Recruiter column | Instahyre jobs beyond AI cap still show recruiters |
| Filters | Min score applies to scored rows only by default |

---

## 14. Validation Checkpoints After Each Phase

Use this table as the go/no-go gate before starting the next phase.

| Phase | Checkpoint | Pass criteria | Status |
|---|---|---|---|
| **A — Foundation** | `db_init` succeeds | All MVP tables exist; Alembic at head | **PASS** |
| **B — Importer** | Import + validate | Counts match CSV; spot checks pass | **PASS** (D8A recovery drill) |
| **C — D1 Dashboard Read Switch** | Streamlit validation + parity | Shadow + dual-write parity PASS | **PASS** |
| **C — D2 Export Promotion** | One acquisition run + export parity | `jobs.csv` from `current_jobs_view` | **PASS** (run 8, 2026-06-02) |
| **D — Descriptions** | One run | Description rows match | **PASS** (dual-write) |
| **D — AI eval** | One run | `ai_status` counts match | **PASS** (D8A cap run) |
| **E — CRM/state** | One run with Instahyre | CRM rows ≥ Instahyre recruiter jobs | **PASS** (D8A) |
| **F — Views** | Export compare | `jobs.csv` rows = view rows | **PASS** (D2) |
| **G — Reset** | `bootstrap` reset | SQLite empty product tables; auth preserved | **PASS** (D7/D8A) |
| **H — Multi-run** | 3+ runs | All parity blocks PASS | **PASS** (runs 11–13, 2026-06-03) |
| **I — Dashboard** | Manual UI review | Pending AI UX acceptable | **PASS** (unit tests; manual optional) |
| **J — Promotion** | Definition of done (§16) | All criteria met | **PASS** (D8B, 2026-06-03) |

If any checkpoint fails: **stop**, roll back to last good flag combination (§11), fix, re-validate.

---

## 15. Rollback / Fallback Procedures

### Operator playbook

#### Symptom: DB writes cause errors mid-run

1. Set `SQLITE_DUAL_WRITE=0` or `SQLITE_ENABLED=0`.
2. Re-run pipeline — CSV path must succeed.
3. Inspect logs and `data/ai_job_agent.db` with DB Browser or `sqlite3`.

#### Symptom: Count mismatch CSV vs DB

1. Do **not** promote SQLite.
2. Run `python scripts/validate_sqlite_parity.py --mode import` and `python scripts/validate_sqlite_parity.py --mode production`.
3. Run `python scripts/identity_inventory.py` for CSV/SQLite orphan signals.
4. If drift is severe: archive → `import_csv_memory.py` (see [PROJECT_COMMAND_REFERENCE.md §10b](./PROJECT_COMMAND_REFERENCE.md#sqlite-product-memory-source-of-truth)).

#### Symptom: Wrong data after reset

1. Restore from `archive/reset-YYYYMMDD-HHMM/`.
2. Run `reset_state.sh` with intended profile.
3. Re-run `import_csv_memory.py` if SQLite enabled.

#### Symptom: D2 DB export fallback or unwanted DB-backed `jobs.csv`

1. Set `SQLITE_EXPORT_FROM_DB=0` (keep `SQLITE_ENABLED=1` / `SQLITE_DUAL_WRITE=1` if desired).
2. Re-run pipeline — legacy in-memory export writes `jobs.csv`.
3. Inspect terminal for `D2 DB export hard parity failed` vs `jobs.csv export_mode=db_current_jobs_view`.

#### Symptom: Need to abandon SQLite entirely (emergency only)

1. `SQLITE_ENABLED=0` on `main.py` and Streamlit.
2. Continue on CSV until DB is repaired or re-imported.
3. Optionally delete `ai_job_agent.db` to avoid confusion (archive first).

### What must always work without SQLite

- `python main.py` with `SQLITE_ENABLED=0`
- `save_to_csv`, `update_historical_jobs`, `update_recruiter_crm`
- Dashboard on CSV
- `reset_state.sh` CSV profiles
- Auth files untouched by normal resets

---

## 16. Definition of Done — SQLite Becomes Source of Truth

**Status: COMPLETE (D8B, 2026-06-03).** Evidence captured during private promotion (operator-local logs; not in public clone).

SQLite is promoted from "shadow memory" to **source of truth**. All gates below satisfied:

### Technical gates

- [x] MVP schema stable (no pending breaking Alembic revisions) — head `004_active_recruiters_view` (D8A T1).
- [x] Importer produces DB matching CSV on a fresh archive restore (D8A T2/O1).
- [x] **≥ 3** consecutive real acquisition runs with `SQLITE_DUAL_WRITE=1` and full parity PASS (runs 11–13, 2026-06-03).
- [x] At least **1** run validated with `AI candidates > DEBUG_LIMIT` and correct `skipped_by_cap` persistence (D8A T4; 66 skipped in cap drill).
- [x] Invariant: `persistence_cohort_count >= ai_scored_count` every run (D8A T5; validators LIFECYCLE PASS).
- [x] Invariant: pending/skipped never blanks prior scored evaluation (D8A T6; cap cohort all brand-new; preservation logic in `historical_persistence.py`).
- [x] Reset profile `bootstrap` clears SQLite + CSV consistently; auth preserved (D7 + D8A T7 live drill).
- [x] `SQLITE_ENABLED=0` rollback verified on same machine (D8A T8).

### Product gates

- [x] D1 dashboard SQLite read path validated (`SQLITE_READ=1`) with CSV fallback preserved and parity checks passing.
- [x] D2 export promotion (core): DB-backed `jobs.csv` from `current_jobs_view` with hard parity gating and legacy fallback (signed off 2026-06-02; run 8 + `validate_dual_write_parity.py --fail-on-error` PASS).
- [x] D2 metadata / full export semantics (D2.1): query/feed metadata persisted via `acquisition_query_runs` + `job_observations.query_run_id`; `current_jobs_view` projects export columns; WARN-only parity (hard-fail opt-in: `SQLITE_METADATA_HARD_PARITY=1`).
- [x] Recruiter CRM from full operational cohort (Instahyre beyond cap included) — D8A P3; 167 recruiters, 80 Instahyre job links.
- [x] Documentation updated in `PROJECT_COMMAND_REFERENCE.md` for DB commands and flags (§10b); D8B SOT posture.

### Operational gates

- [x] `archive_state.sh` + reset + import + run documented as standard recovery path (D7 + D8A O1 live drill).
- [x] Known issue list empty for parity blockers (D8A O2; all validators PASS, zero warnings).

### After promotion

| Component | Role |
|---|---|
| SQLite | Source of truth |
| CSV | Generated export / backup / handoff |
| `validate_sqlite_parity.py --mode production` | Daily regression check after runs (CI: `--fail-on-error`) |
| `validate_dual_write_parity.py` | Deprecated alias for `--mode csv-mirror-sync` |
| Importer | Recovery tool, not daily path |

---

## Appendix A — Operator commands (implemented)

Canonical workflows and PASS/WARN/FAIL semantics: [PROJECT_COMMAND_REFERENCE.md §10b](./PROJECT_COMMAND_REFERENCE.md#sqlite-product-memory-source-of-truth).

### D8B default (no env)

```bash
export OPENAI_API_KEY="..."
python main.py
python scripts/validate_sqlite_parity.py --mode production --fail-on-error
python scripts/export_csv_memory.py --all   # before SOT validator when write-primary
python scripts/validate_sqlite_parity.py --mode source-of-truth --fail-on-error
streamlit run dashboard/app.py
```

### Bootstrap / import (recovery)

```bash
python scripts/db_init.py
python scripts/import_csv_memory.py
python scripts/validate_sqlite_parity.py --mode import --fail-on-error
```

### Emergency rollback

```bash
SQLITE_ENABLED=0 python main.py
```

Legacy opt-in examples (pre-D8B promotion): [Appendix D — Historical promotion runbooks](#appendix-d--historical-promotion-runbooks).

---

## Appendix B — Mapping to architecture doc phases

| Architecture doc phase | Implementation plan phase |
|---|---|
| Phase 1 Schema design | A |
| Phase 2 Importer | B |
| Phase 3 Dual write | C, D, E |
| Phase 4 Dual-write validation | H |
| Phase 5 Dashboard switch | I |
| Phase 6 SQLite source of truth | J |
| Phase 7 Reset tooling | G |
| Phase 8 CSV retirement | J (export-only) |

---

## Appendix D — Historical promotion runbooks

Preserved for audit and rollback drills. **Not required for daily use** after D8B (see [PRODUCTION_OPERATIONS.md](./PRODUCTION_OPERATIONS.md)).

### D4 pipeline read (Plan B)

```bash
SQLITE_ENABLED=1 SQLITE_DUAL_WRITE=1 SQLITE_PIPELINE_READ=1 python main.py
```

Confirm: `Pipeline historical index: SQLite`, `Pipeline description store: SQLite`. Optional: `SQLITE_QUERY_STATE_READ=1` for LinkedIn cooldown from DB.

### D5 write-primary (Plan C)

```bash
SQLITE_ENABLED=1 SQLITE_DUAL_WRITE=1 SQLITE_PIPELINE_READ=1 SQLITE_WRITE_PRIMARY=1 \
SQLITE_EXPORT_HISTORICAL_CSV=1 SQLITE_EXPORT_DESCRIPTIONS_CSV=1 SQLITE_EXPORT_CRM_CSV=1 \
python main.py
```

Staged rollout used all `EXPORT_*=1` first; D8B defaults disable historical/descriptions/CRM CSV export.

### D6 dashboard (Plan D)

```bash
SQLITE_ENABLED=1 SQLITE_READ=1 SQLITE_DASHBOARD_WRITE=1 streamlit run dashboard/app.py
```

### D7 recovery export + SOT

```bash
python scripts/export_csv_memory.py --all
python scripts/validate_sqlite_parity.py --mode source-of-truth --fail-on-error
```

Runtime gates now use `sqlite_flag()` in `src/db/config.py` (remediation 2026-06) so env exports match config defaults when testing overrides.

---

## Appendix C — Core invariant (carry on every PR)

> **All valid deduped and description-enriched jobs persist in SQLite, whether or not they are AI-scored in the current run.**

If a change violates this invariant, it must not ship — regardless of test coverage.
