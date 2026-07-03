# SQLite Product Memory Architecture

Durable planning reference for migrating `ai-job-agent` from CSV persistence to SQLite while preserving the stabilized lifecycle model.

This document is intentionally product-oriented first and technical second. It defines what the product should remember, what can be reset, and how SQLite should become the local source of truth before any future Postgres/cloud migration.

---

## 1. Product Memory Philosophy

`ai-job-agent` should behave less like a scraper and more like a local-first job intelligence system.

Each acquisition run should make the product smarter:

- It should remember jobs it has seen before.
- It should recognize repeat jobs across sources and runs.
- It should preserve AI scores and reasoning.
- It should retain recruiter history.
- It should keep user workflow state such as applied, rejected, interview, offer, and notes.
- It should allow operational resets without casually erasing product memory.

The core product principle is:

> Resets should clear the workspace or experiment surface, not erase durable intelligence unless explicitly requested.

The second core principle is:

> AI scoring limits are workload controls, not persistence controls.

All valid deduped and description-enriched jobs should persist. The AI cap should only decide how many jobs get scored in a run.

---

## 2. Memory Classes

### Permanent Product Memory

This is what the product should remember long term.

| Memory | Product Meaning |
|---|---|
| Job identity | A stable understanding of a job across runs and sources |
| Job observations | When and where the job was seen |
| Job descriptions | Cached descriptions so the system does not repeatedly fetch them |
| AI evaluations | Score, reasoning, status, model, and evaluation time |
| Recruiters | People discovered through jobs and feeds |
| Recruiter-job links | Which recruiters are connected to which jobs |
| User workflow state | Applied, rejected, interview, offer, notes, pipeline stage |
| Acquisition history | Which sources, queries, and feeds produced jobs |
| Reset history | What operational resets happened and what they affected |

### Session Memory

This is useful for the latest run but should not be treated as product truth by itself.

| Memory | Product Meaning |
|---|---|
| Current run job list | What this run saw after acquisition/filtering |
| Current export | A generated view of latest operational jobs |
| AI batch queue | Jobs selected for scoring in this run |
| Skipped-by-cap set | Valid jobs not scored because of run budget |
| Query execution trace | Which queries ran in this run and in what order |

### Operational Artifacts

These help the system operate but are not core product memory.

| Artifact | Recommended Handling |
|---|---|
| Browser auth JSON | Keep file-based and private |
| Terminal logs | Keep file/log based |
| Playwright traces/screenshots | Keep file-based |
| Archive tarballs | Keep file-based |
| CSV exports | Generate from SQLite for debugging or handoff |
| Temporary validation outputs | Keep outside durable product tables unless explicitly imported |

---

## 3. Lifecycle Persistence Semantics

The stabilized lifecycle should remain the foundation of the database design.

Current intended lifecycle:

1. Acquire jobs from LinkedIn, InstaHyre, Greenhouse, Lever, WeWorkRemotely, and future sources.
2. Normalize fields.
3. Resolve identity using `JOB_KEY_V2`.
4. Split historically known jobs from brand-new jobs.
5. Apply Stage 1 filtering to brand-new jobs.
6. Deduplicate accepted jobs.
7. Enrich descriptions.
8. Build the full persistence cohort.
9. Split AI scoring workload from persistence.
10. Persist all valid jobs.
11. Score only the capped AI cohort.
12. Export latest operational view.
13. Sync recruiter CRM from the full operational cohort.

SQLite must preserve this invariant:

| Cohort | Meaning | Must Persist? |
|---|---|---|
| Acquired jobs | Raw source output | No, only summary/run traces are needed |
| Stage 1 accepted | Jobs that passed product relevance filter | Usually yes after dedup/enrichment |
| Deduped jobs | Unique valid jobs | Yes |
| Description-enriched jobs | Jobs ready for memory/scoring | Yes |
| AI scoring jobs | Capped subset sent to AI | Yes |
| Pending/skipped jobs | Valid jobs not scored this run | Yes |
| Session export jobs | Latest operational cohort after final merge | Yes, as a derived view |

The database should make it impossible to accidentally persist only the scored subset.

---

## 4. Historical Continuity Principles

Historical continuity means the product recognizes that a job or recruiter seen today may already have memory from an earlier run.

Continuity rules:

- A repeated job should keep its stable identity.
- Previous AI score/reason should remain available if the job is skipped by cap later.
- User workflow state should survive reacquisition.
- A repeated recruiter should update last-seen context, not create a duplicate person.
- New observations should be added without destroying earlier useful knowledge.

Example:

> If a job was scored last week, then appears again today but is skipped by the scoring cap, the system should record today's observation while keeping last week's score visible.

Historical continuity is the difference between "scrape results" and "product memory."

---

## 5. Recruiter CRM Continuity Principles

Recruiter memory should behave like a lightweight CRM.

The system should remember:

- Recruiter identity
- First seen date
- Last seen date
- Source where the recruiter appeared
- Jobs connected to the recruiter
- Recruiter title and company, when available
- Outreach state
- Reply state
- Notes
- Whether the recruiter appears active in recent runs

Recruiter identity and recruiter observations should be separate.

Why:

- The same recruiter may appear across many jobs.
- Recruiter title/company can change.
- InstaHyre may provide richer recruiter metadata than LinkedIn.
- A recruiter should not disappear from CRM just because one job is no longer active.

Product rule:

> Recruiter identity accumulates over time; recruiter observations explain when and where the recruiter was seen.

---

## 6. AI Evaluation Lifecycle Principles

AI evaluations should become durable evaluation history, not just fields on the latest job row.

The system should remember:

- AI status
- Score
- Reason
- Model name
- Prompt/profile version when available
- Evaluation timestamp
- Whether evaluation failed
- Whether a job was skipped due to cap

Long-term rule:

> AI evaluations should accumulate historically. The dashboard should show the latest useful evaluation by default.

Do not overwrite a valid score/reason with a blank pending or skipped result.

Valid overwrite/update behavior:

| Incoming State | Existing Evaluation | Desired Behavior |
|---|---|---|
| `scored` | none | Save as latest evaluation |
| `scored` | previous scored | Add new evaluation; latest becomes default |
| `skipped_by_cap` | previous scored | Record run status but keep previous score visible |
| `pending` | previous scored | Keep previous score visible |
| `failed` | previous scored | Record failure, keep previous score visible |

---

## 6A. Hiring Manager Merge (Dual-Write)

Runtime acquisition dual-write (`_upsert_jobs` in `src/db/services/dual_write.py`) must not clobber a real `jobs.hiring_manager` with scrape sentinels.

Sentinel values (case-insensitive, trim-first): `NULL`, blank, `Not Specified`, `Unknown`, `nan`, `none`.

| Incoming scrape value | Existing DB value | Desired behavior |
|---|---|---|
| real name | sentinel | update to incoming |
| real name | real name | update to incoming |
| sentinel | real name | preserve existing |
| sentinel | sentinel | preserve existing (no meaningful change) |

Implementation: SQL `CASE` on conflict — when incoming is sentinel, keep `Job.hiring_manager`; otherwise accept `excluded.hiring_manager`. Helper: `is_hiring_manager_sentinel()` / `incoming_hm_is_sentinel_sql()` in `src/db/services/recruiter_enrichment.py`.

Dashboard HM edits and Task C backfill apply paths are separate; this rule applies to acquisition runtime upserts only.

---

## 6B. Posted Date Fields (Dual-Write)

Runtime acquisition derives ISO `posted_at_date` and `age_days` from relative `time_posted` ([`src/agent/posted_date_derive.py`](../src/agent/posted_date_derive.py)), wired in `main.py` and `_upsert_jobs`.

On conflict, dual-write preserves existing non-null values:

| Field | Merge rule |
|---|---|
| `posted_at_date` | `COALESCE(incoming, existing)` |
| `age_days` | `COALESCE(incoming, existing)` |

**Operator backfill (not schema changes):** [`scripts/backfill_posted_at_date.py`](../scripts/backfill_posted_at_date.py) (anchor from `last_seen`); [`scripts/backfill_linkedin_posted_dates.py`](../scripts/backfill_linkedin_posted_dates.py) (Playwright re-scrape for `time_posted=Unknown`).

**Dashboard:** Job Listings Posted column still uses `last_seen` fallback — display phase is future.

---

## 6C. HM Repair Tooling (One-Time Operator)

Complement to §6A forward protection. Both write **`jobs.hiring_manager` only**; `recruiter_job_links` remain append-only.

| Task | Cohort | Script |
|---|---|---|
| **C — Backfill** | Sentinel HM, **no** `recruiter_job_links` | `scripts/backfill_linkedin_hiring_managers.py` |
| **E — Overwrite repair** | Sentinel HM, **exactly one** link, valid recruiter name | `scripts/repair_linkedin_hm_overwrite_cohort.py` |

Canonical commands: [PROJECT_COMMAND_REFERENCE.md §8](./PROJECT_COMMAND_REFERENCE.md).

---

## 7. `ai_status` Semantics

Current CSV semantics should evolve into database-backed AI lifecycle semantics.

Recommended statuses:

| Status | Product Meaning |
|---|---|
| `pending` | Job is eligible for AI scoring but has not been scored yet |
| `skipped_by_cap` | Job was valid and persisted but not scored because of run budget |
| `scored` | AI produced score/reason |
| `failed` | AI scoring was attempted but failed |
| `not_required` | Jobs intentionally excluded from AI scoring (user-managed CRM / sync imports) |

Important rules:

- `ai_score` should be nullable.
- `ai_score = 0` should only mean AI truly scored the job as `0`.
- Unscored jobs should not be treated as bad-fit jobs.
- Latest dashboard score should come from the latest valid `scored` evaluation.
- Run-level skipped/pending state should not erase historical scored state.

### `not_required` lifecycle

| Stage | Behavior |
|-------|----------|
| **Writers** | Instahyre Interested sync (`model=instahyre_interested_sync`); `materialize_fully_processed_job()` when historical stage is user-managed |
| **Readers** | Dashboard score badge “Not Required”; pipeline routing treats `not_required` as explicit AI state |
| **Routing guard** | `_historical_job_needs_ai_fallback()` returns false for `not_required` — never re-queued for OpenAI scoring |
| **Dual-write protection** | Runtime dual-write does not downgrade `not_required` → `pending` on re-write |
| **Parity** | Production/import cumulative checks may WARN on `not_required` aggregate — expected DB-only CRM state, not a failure |

---

## 7A. User-Managed Pipeline Stages

Canonical constants: [`src/agent/pipeline_stages.py`](../src/agent/pipeline_stages.py) (shared by agent, dual-write, dashboard).

| Category | Stages | AI scoring |
|----------|--------|------------|
| **Discovery** | `New`, `Saved` | Eligible (subject to cap and min-score filters in dashboard) |
| **User-managed (CRM)** | `Applied`, `HR Screen`, `Interview`, `Final Round`, `Offer`, `Rejected`, `Ghosted` | **`not_required`** — bypass AI evaluation |

**Promotable vs protected (acquisition merge):**
- **Promotable:** `""`, `New` — may promote to `Applied` when scrape/sync sets `applied=True`.
- **Protected:** `Saved` and all user-managed stages — operator/sync state preserved unless explicit `New`→`Applied` promotion.

**Incremental routing** (`main.py`): historical hit with user-managed `pipeline_stage` → **fully_processed** (skip Stage-1, dedup, descriptions, AI). Historical hit needing AI fallback only when not user-managed and not `not_required`.

---

## 7B. Instahyre Interested Sync Persistence

Post-feed synchronization phase (when `INSTAHYRE_MAX_RUNS ≠ 0`). List-only harvest; stubs never enter the main `all_jobs` pipeline.

**Persist path** (`persist_instahyre_interested_sync`):

1. `jobs` — minimal list metadata from Interested filter cards
2. `user_job_state` — `_merge_user_job_state_payload` (Applied promotion; stage protection for Saved+)
3. Early `acquisition_run` + `job_observations` (`query_id=interested_sync`) — updates `first_seen` / `last_seen` even when stage protected
4. `ai_evaluations` — `not_required` rows for user-managed stages

**Export cohort isolation:** Interested-only jobs in `historical_jobs_view`; excluded from `current_jobs_view` / `jobs.csv` until picked up by a full acquisition dual-write.

Operator detail: [PROJECT_COMMAND_REFERENCE.md §5](./PROJECT_COMMAND_REFERENCE.md#5-instahyre-specific-controls).

---

## 7D. AI Refresh Evaluations (re-score path)

Separate orchestration entry from acquisition. **Does not** scrape, fetch descriptions, or call `dual_write_runtime_snapshot`.

| Component | Role |
|-----------|------|
| `scripts/run_ai_refresh.py` | CLI entry: cohort load → hydrate from `job_descriptions` → `run_batch_ai_scoring` → append evals |
| `src/agent/ai_scoring_orchestrator.py` | Shared batch scoring loop (also used by `main.py` after description fetch) |
| `src/db/read/ai_refresh_cohort.py` | Preset cohort selection (`backlog`, `discovery`) |
| `ai_refresh_runs` | Run lifecycle + stats (preset, cohort_size, scored_count, persist_skipped_count, batch_failures) |
| `ai_evaluations.ai_refresh_run_id` | Optional FK linking refresh-scored rows to their run |

**Dashboard (AI Refresh Health):** Two-row KPI layout for the latest completed run; history table omits cap-skipped operator metrics. Operator Controls preview shows cohort matched, eligible (with description), and estimated batches only.

**Evaluation write policy (rescoring):**

- Incoming scored job with score + reason → **INSERT** new `ai_evaluations` row (`model=ai_refresh`, `evaluated_at=now`).
- `latest_ai_evaluations_view` selects newest row per `job_id` — dashboard and `historical_jobs_view` pick up the refresh automatically.
- Jobs with `ai_status=not_required` are excluded from cohort and skipped on write (never downgraded).
- No updates to `jobs`, `job_observations`, or recruiter tables from refresh.

**Cohort presets (summary):**

| Preset | Intent |
|--------|--------|
| `backlog` | Discovery stages; `pending` / `skipped_by_cap` / incomplete `scored`; any listing status |
| `discovery` | Open `New` with persistable description; includes healthy `scored` for profile refresh |

Operator detail: [PROJECT_COMMAND_REFERENCE.md §10](./PROJECT_COMMAND_REFERENCE.md#ai-refresh-scriptsrun_ai_refreshpy) and [PRODUCTION_OPERATIONS.md §5.1](./PRODUCTION_OPERATIONS.md#51-refresh-ai-evaluations-re-score-without-scrape).

---

## 7E. LinkedIn Applied auto-promotion

When the lifecycle monitor detects that the operator has applied on LinkedIn:

1. **`promote_job_to_applied_if_eligible`** sets `user_job_state.pipeline_stage=Applied` for discovery-stage jobs.
2. **`set_monitor_exempt`** sets `jobs.listing_status=monitor_exempt` (Scheduler B skips the job).
3. **`should_skip_expensive_acquisition`** routes the job through the fully-processed acquisition path on subsequent runs.

Contrast with Instahyre Interested sync (acquisition-time list harvest) and dashboard **Applied ✓** (manual Recommended Actions). Full operator detail: PRODUCT_STATUS_SUMMARY.md.

---

## 7C. Job listing availability (`listing_status`) — historical note

**Current model (Task 4 / TD10):** Listing availability is tracked on `jobs.listing_status`, written by the lifecycle monitor (Scheduler B). Dashboard and Recommended Actions use `listing_status` exclusively (`open` + `closed` visible in Job Listings; `removed` hidden; RA `open` only).

**Retired (pre–Task 4):** Post-acquisition inactivity sweep on `job_observations.currently_active` — removed in migration `014_drop_currently_active`. See PRODUCT_STATUS_SUMMARY.md.

**Not the same as:**

- **Recommended Actions age** — uses `first_seen` only (Needs Review queue).
- **Posted display** — Job Listings Posted column uses `last_seen` fallback, not `posted_at_date` yet.
- **CRM `recruiter_stage`** — recruiter workflow, not acquisition sighting.

**Dashboard visibility:** `listing_status` drives discovery visibility; user-managed pipeline stages remain visible per product §5A.

---

## 8. Reset Philosophy And Profiles

Reset profiles should continue to express product intent, not just file deletion.

### Existing Reset Profile Meanings

| Profile | Product Intent |
|---|---|
| `bootstrap` | Clean validation run; reset job memory, descriptions, query state, and CRM while preserving auth |
| `acquisition` | Reset current acquisition/export surface while preserving durable memory |
| `crm-preserving` | Reset acquisition/job memory while preserving recruiter CRM |
| `full` | Full runtime reset except auth by default |

### SQLite Reset Philosophy

When SQLite becomes source of truth, reset profiles should clear table groups rather than CSV files.

Recommended table reset scope:

| Profile | Likely SQLite Reset Scope |
|---|---|
| `bootstrap` | Clear jobs, observations, descriptions, evaluations, user state, query state, CRM tables |
| `acquisition` | Clear latest run/export tables and query state; preserve jobs, descriptions, evaluations, CRM |
| `crm-preserving` | Clear jobs/observations/descriptions/evaluations/query state; preserve recruiter tables |
| `full` | Clear all product/runtime tables; preserve auth files unless explicitly requested |

Auth should remain file-based and preserved unless the user explicitly chooses an auth reset.

---

## 9. Operational Invariants

These are the checks the system should keep true across CSV, SQLite dual-write, and eventual SQLite-only operation.

| Invariant | Why It Matters |
|---|---|
| Deduped/enriched count equals persisted cohort count | Prevents scored-only persistence regressions |
| AI scored count is less than or equal to AI cap | Ensures scoring workload is controlled |
| Persisted cohort can exceed AI scored count | Confirms cap does not truncate memory |
| `ai_score` can be blank only when not scored | Keeps unscored separate from bad-fit |
| `ai_score = 0` only appears with `ai_status = scored` | Preserves meaning of true AI rejection |
| Recruiter CRM sync uses full operational cohort | Prevents missed recruiter contacts |
| Historical score/reason is not blanked by pending/skipped | Preserves continuity |
| Query state records executed curated feeds | Keeps orchestration auditable |
| Reset preserves auth unless explicitly requested | Avoids unnecessary login breakage |

---

## 10. Source-Of-Truth Philosophy

Source of truth means:

> The place the product trusts when CSVs, logs, dashboard state, or temporary outputs disagree.

Target source-of-truth model:

| System Area | Source Of Truth |
|---|---|
| Job identity | SQLite `jobs` |
| Job sightings/current activity | SQLite `job_observations` |
| Job descriptions | SQLite `job_descriptions` |
| AI score/reason/status | SQLite `ai_evaluations` plus latest evaluation view |
| Recruiters | SQLite `recruiters` |
| Recruiter/job relationships | SQLite `recruiter_job_links` |
| User workflow state | SQLite `user_job_state` |
| Current dashboard view | SQLite view generated from source tables |
| CSV files | Derived exports/debug artifacts |
| Auth/session cookies | File-based auth JSON |
| Terminal output | Operational evidence, not product memory |

Once SQLite is active, CSVs should be regenerable from the database.

---

## 11. Recommended SQLite Table Architecture

### Product Tables

| Table | Purpose | Source Of Truth? |
|---|---|---|
| `jobs` | Canonical job identity | Yes |
| `job_observations` | Every run/source observation of a job | Yes |
| `job_descriptions` | Description cache | Yes |
| `ai_evaluations` | AI score/reason/status history | Yes |
| `user_job_state` | Applied/rejected/interview/offer/notes | Yes |
| `recruiters` | Canonical recruiter identity | Yes |
| `recruiter_observations` | Where/when recruiter data was observed | Yes |
| `recruiter_job_links` | Recruiter-to-job relationships | Yes |

### Operational Tables

| Table | Purpose | Source Of Truth? |
|---|---|---|
| `acquisition_runs` | One row per pipeline run | Yes for run history |
| `ai_refresh_runs` | One row per manual/CLI AI refresh run (re-score without scrape) | Yes for refresh audit |
| `acquisition_query_runs` | LinkedIn query/InstaHyre feed execution records | Yes for query/feed history |

**Run provenance:** Production may trigger the pipeline manually (`python main.py`) or via macOS launchd ([SCHEDULER_SETUP.md](./SCHEDULER_SETUP.md)). Both paths use the same dual-write and SQLite gates; the scheduler is external orchestration only.
| `query_cooldown_state` | Current query cooldown/orchestration state | Yes for orchestration |
| `reset_events` | Reset profile, archive ID, resources affected | Yes for reset audit |

### Shipped views (Alembic)

| View | Purpose |
|---|---|
| `current_jobs_view` | Latest export cohort (`jobs.csv` shape); KPI “Latest Acquisition” |
| `historical_jobs_view` | Full job memory for dashboard table and progression |
| `latest_ai_evaluations_view` | Latest valid AI evaluation per job |
| `active_recruiters_view` | CRM dashboard view |
| `latest_acquisition_run_view` | Last dual-write run timestamp (dashboard “Last acquisition refresh”) |

### Deferred views (Phase 5 — not in schema)

| View | Purpose |
|---|---|
| `run_summary_view` | Operational metrics per run |
| `source_effectiveness_view` | Source/query performance over time |

Dashboard analytics (Job Search Progression, Source Distribution, Pipeline analytics expander) are computed in-app from `historical_jobs_view` + visibility rules — not from deferred SQL views.

### Dashboard Hiring Manager enrichment (Phase 3B)

When an operator edits **Hiring Manager** in Job Listings with `SQLITE_DASHBOARD_WRITE=1`:

| Table | Write behavior |
|-------|----------------|
| `jobs` | `hiring_manager` updated (current display for the job row) |
| `recruiters` | Upsert by `recruiter_key` (`name.strip().lower()`); new rows get `source=job_editor` |
| `recruiter_job_links` | **Append-only** — insert `(recruiter_id, job_id)` if missing; `UNIQUE(recruiter_id, job_id)` prevents duplicates; **no deletes** on HM change |

Implementation: [`src/db/services/recruiter_enrichment.py`](../src/db/services/recruiter_enrichment.py) via [`dashboard_write.persist_dashboard_job_edits()`](../src/db/services/dashboard_write.py). CRM `jobs_connected` in `active_recruiters_view` counts live links from `recruiter_job_links`, not `jobs.hiring_manager` alone.

Acquisition-time recruiter extract (Instahyre detail pages) uses the same tables via dual-write; dashboard HM edit is a separate job-bound path. **LinkedIn acquisition** extracts `hiring_manager` via primary BEM selector + flagship3 poster-section fallback ([`scraper/linkedin.py`](../scraper/linkedin.py)); dual-write §6A prevents sentinel re-scrapes from clobbering real values.

**Outreach schema vs CRM UI:** `recruiters` stores `outreach_sent`, `recruiter_replied`, `last_outreach_date`, `last_response_date`, and `touchpoint_count` (normalized in dashboard loaders). The Streamlit CRM table does **not** surface these columns — operator edits are limited to recruiter stage and HM-driven enrichment today.

### Outreach Intelligence V1

Separate from Recruiter Intelligence — **no CRM coupling**, no FK to `jobs` or `recruiters`.

| Table | Role |
|-------|------|
| `outreach_attempts` | One row = one outreach attempt; opportunity-centric outreach attempt log |

Key fields: `person_name`, `company`, `outreach_channel`, `status`, `date_contacted`, optional `follow_up_date`, `notes`, optional soft link `opportunity_id` (`job_key_v2` text) and `opportunity_url` snapshot. **V1.1:** `hiring_signal_type` (required on new creates; nullable for legacy rows) and optional `hiring_signal_url`. **V1.3:** `outreach_type` (`hiring_signal` vs `job_outreach`).

**Hiring signal types (9):** `linkedin_hiring_post`, `founder_post`, `recruiter_message`, `whatsapp_referral`, `personal_referral`, `mentor_referral`, `direct_outreach`, `job_listing` (Job Outreach path), `other`.

**V1.2 ingestion:** LinkedIn post URL Fetch Details in Add Outreach — modules under [`src/outreach/`](../src/outreach/); Playwright + OpenAI prefill; Save is only persistence action.

**V1.3 Job Outreach:** DB-driven prefill from job row + description + recruiter ([`src/db/read/job_outreach.py`](../src/db/read/job_outreach.py), [`src/agent/job_outreach_prefill.py`](../src/agent/job_outreach_prefill.py)); no Playwright.

**Creation (dashboard only):** manual + job-linked creation via Add Outreach form (optional Link to job from Job Listings cohort / `dashboard_editor_df`). New outreach requires hiring signal type. No auto-create on Applied or HM edit. No recruiter-originated or person-first workflows.

**Read vs write:** loads when `SQLITE_READ=1`; add/edit require `SQLITE_DASHBOARD_WRITE=1` (read-only KPIs, filters, and table when writes are off).

**Reset profiles:** `outreach_attempts` truncated on `bootstrap` / `full`; **preserved** on `crm-preserving` and `acquisition` (operator memory survives job wipes).

Implementation: [`src/db/services/outreach_write.py`](../src/db/services/outreach_write.py), [`dashboard/outreach_ui.py`](../dashboard/outreach_ui.py). Does **not** write to `recruiters.outreach_*` columns.

### Dashboard write-back paths (D8B)

| Operator action | Write path | Tables |
|-----------------|------------|--------|
| Job Listings pipeline stage / flags | `persist_dashboard_job_edits()` | `jobs`, `user_job_state` |
| Hiring Manager edit (3B) | `sync_recruiter_from_hiring_manager()` | `jobs`, `recruiters`, `recruiter_job_links` |
| Recruiter CRM stage edit | recruiter stage upsert in `dashboard_write.py` | `recruiters` |
| Recommended Actions **Applied ✓** (3A.1) | `mark_job_applied()` | `user_job_state` (`pipeline_stage=Applied`, `applied=True`) |
| Outreach Intelligence V1–V1.3 add / table edit | `outreach_write.py` | `outreach_attempts` only |

Implementation: [`src/db/services/dashboard_write.py`](../src/db/services/dashboard_write.py). Requires `SQLITE_DASHBOARD_WRITE=1`.

---

## 12. CSV-To-SQLite Mapping

| Current File | Future Role | SQLite Mapping |
|---|---|---|
| `historical_jobs.csv` | Import source, then retired/exported | `jobs`, `job_observations`, `ai_evaluations`, `user_job_state` |
| `jobs.csv` | Derived current export | `current_jobs_view` export |
| `job_descriptions.csv` | Import source, then retired/exported | `job_descriptions` |
| `recruiter_crm.csv` | Import source, then retired/exported | `recruiters`, `recruiter_observations`, `recruiter_job_links` |
| `job_state.csv` | Import source, then retired/exported | `user_job_state` |
| `.linkedin_query_state.json` | Migrated operational state | `query_cooldown_state`, `acquisition_query_runs` |
| `linkedin_auth.json` | Remains file-based | Not migrated |
| `instahyre_auth.json` | Remains file-based | Not migrated |

---

## 13. Migration phases (completed)

| Phase | Scope | Implementation | Status |
|-------|--------|----------------|--------|
| 1 | Schema design | Alembic MVP tables + views | Done (D0 foundation) |
| 2 | Read-only importer | `import_csv_memory.py` | Done (Phase B) |
| 3 | Dual write | End-of-run persistence cohort | Done (D3–D5) |
| 4 | Production validation | `validate_sqlite_parity.py --mode production` | Done (D8B; legacy `validate_dual_write_parity.py` → csv-mirror-sync) |
| 5 | Dashboard read switch | `current_jobs_view`, loaders | Done (D1/D8B) |
| 6 | SQLite source of truth | D8B default flags | Done (2026-06-03) |
| 7 | Reset tooling | Bootstrap truncates DB + CSV | Done (D7) |
| 8 | CSV export path | `export_csv_memory.py`; not product memory | Done (D8B write-primary) |

Operator reference: [PRODUCT_STATUS_SUMMARY.md](./PRODUCT_STATUS_SUMMARY.md), [PRODUCTION_OPERATIONS.md](./PRODUCTION_OPERATIONS.md).

---

## 14. Dual-write strategy (completed)

Dual-write remains **on by default** (`SQLITE_DUAL_WRITE=1`). SQLite is authoritative under write-primary; CSV is an **emergency/export path (D8B)**, not daily product memory.

Historical rollout approach (completed):

1. SQLite writes at end of `main.py` persistence cohort.
2. Validators after each run:
   - **`--mode production`** (scheduler + daily ops): strict on SQLite and this-run `jobs.csv` cohort; stale optional `historical_jobs.csv` rows warn when `SQLITE_EXPORT_HISTORICAL_CSV=0` (default).
   - **`--mode source-of-truth`**: strict bidirectional CSV export parity after `export_csv_memory.py`.
3. Dashboard promoted to SQLite reads/writes (D6/D8B).
4. CSV mirrors refreshed via `export_csv_memory.py --all` when needed for SOT or handoff.

Minimum dual-write acceptance checks (still used for regression):

| Check | Expected |
|---|---|
| Description rows | Match deduped/enriched count |
| DB persisted jobs | Match persistence cohort |
| `jobs.csv` rows | Match `current_jobs_view` rows |
| `ai_status` counts | Match between CSV and DB view |
| Recruiter rows | Match expected CRM behavior |
| Historical score preservation | Pending/skipped does not blank scored history |

---

## 15. Dashboard Evolution Strategy

The dashboard should evolve from reading CSVs to reading SQLite views.

### Current state (D8B)

Dashboard reads from SQLite views by default (`SQLITE_READ=1`). CSV loaders are fallback when flags are off or on read errors.

### Target state (achieved)

Dashboard reads from views (default `SQLITE_READ=1`):

- `historical_jobs_view` — primary job memory (`dashboard_df` after visibility in `data_flow.py`)
- `current_jobs_view` — latest acquisition export cohort
- `latest_acquisition_run_view` — refresh timestamp
- `active_recruiters_view` — CRM
- `latest_ai_evaluations_view` — score/reason join

Deferred (Phase 5): `run_summary_view`, `source_effectiveness_view`

Conceptual dashboard tabs:

| Dashboard Area | Product Question |
|---|---|
| Latest Jobs | What should I act on now? |
| Pending AI | What was persisted but not scored yet? |
| Historical Jobs | What has the system learned over time? |
| Recruiter CRM | Who should I track or contact? |
| Run Summary | What happened in the latest acquisition run? |
| Source Quality | Which sources and queries produce useful jobs? |

Dashboard product rule:

> The default view should show latest actionable state, while history remains available for context and analytics.

---

## 16. Long-Term Evolution Path

### Stage 1: CSV source of truth

Historical pre-migration architecture.

### Stage 2: SQLite dual write

Completed — SQLite receives persistence cohort writes; CSV optional.

### Stage 3: SQLite source of truth (current)

**Current architecture (D8B).** SQLite is local product memory; CSV is generated export / backup.

### Stage 4: SQLite With Stronger Product Features

Possible additions:

- AI rescore history
- Prompt/profile versioning
- Source effectiveness analytics
- Recruiter outreach workflow
- Run comparison
- Backfill scoring queue

### Stage 5: Postgres/Cloud Option

Move to Postgres or a hosted database when the product needs:

- Multiple users
- Cloud-hosted dashboard
- Background workers
- API access
- Public production deployment
- Team/shared recruiter CRM
- Stronger concurrent writes

If SQLite tables are designed cleanly, the future Postgres migration should be mostly infrastructure and operations work rather than a full product logic rewrite.

---

## 17. Deferred Decisions

These decisions can wait until after SQLite schema validation:

- Whether to keep every raw scraper payload.
- How much AI prompt text to store.
- Whether to version user profiles formally in DB (file-based v2 profile exists: `config/profiles/ai_candidate_profile.example.md`).
- Whether to support multiple resumes/personas.
- Whether recruiter identity should use name-only or richer matching.
- Whether acquisition logs should live in DB or files.
- Whether Postgres should be self-hosted, managed, or abstracted behind an ORM.

---

## 18. Summary

The SQLite migration should establish a durable product memory layer.

The target architecture is:

```text
SQLite = product memory and source of truth
CSV = generated export/debug artifact
Files = auth, logs, archives, diagnostics
Dashboard = reads from SQLite views
Reset tooling = clears intentional table groups
Future Postgres = cloud evolution path, not immediate need
```

The most important invariant to preserve is:

> All valid deduped and description-enriched jobs persist, whether or not they are AI-scored in the current run.

