# Production Operations

Step-by-step operator guide for **daily use** and **pre-production reset** after D8B SQLite promotion. **Canonical source** for live operator procedures (reset §2, daily workflow §3).

**System overview (milestones, architecture, roadmap):** [PRODUCT_STATUS_SUMMARY.md](./PRODUCT_STATUS_SUMMARY.md)  
**Codebase navigation:** [REPOSITORY_MAP.md](./REPOSITORY_MAP.md)  
**Command catalog and flags:** [PROJECT_COMMAND_REFERENCE.md](./PROJECT_COMMAND_REFERENCE.md) §10b  
**Migration history:** [SQLITE_IMPLEMENTATION_PLAN.md](./SQLITE_IMPLEMENTATION_PLAN.md)  
**Production scheduling (macOS):** [SCHEDULER_SETUP.md](./SCHEDULER_SETUP.md)

---

## 1. System posture

| Layer | Role |
|-------|------|
| **SQLite** (`data/ai_job_agent.db`) | Default **source of truth** for product memory (jobs, evaluations, descriptions, recruiters, run history) |
| **CSV under `data/`** | Export, backup, handoff, and recovery — not the daily read path when D8B flags are on |
| **Auth JSON** | `linkedin_auth.json`, `instahyre_auth.json` — file-only, never in DB |
| **Config** | `config/linkedin_queries.json`, `config/instahyre_feeds.json`, `config/profiles/ai_candidate_profile.example.md` |
| **Flags** | D8B defaults in `src/db/config.py` via `sqlite_flag()` — **no `SQLITE_*` env exports** required for normal runs |

Emergency CSV-only: `SQLITE_ENABLED=0` on `main.py` and Streamlit.

---

## 2. Pre-production DB reset workflow

Use when starting a **clean daily cadence** from a known baseline (recommended before first production use after migration).

### 2.1 Archive current state

```bash
./scripts/archive_state.sh
# Note RESET_ID from output, e.g. reset-20260603-1430
```

Optional: `./scripts/archive_state.sh --compress`

### 2.2 Stop running processes

Stop any in-flight `python main.py` and `streamlit run dashboard/app.py`.

### 2.3 Preview bootstrap reset

```bash
./scripts/reset_state.sh --archive-id reset-YYYYMMDD-HHMM --profile bootstrap --dry-run
```

Confirm plan lists SQLite table truncation (default-on `SQLITE_ENABLED` via `sqlite_flag()` — no env export required).

### 2.4 Apply bootstrap reset

```bash
./scripts/reset_state.sh --archive-id reset-YYYYMMDD-HHMM --profile bootstrap --no-confirm
```

Or use `python scripts/reset_runtime.py` directly (see [PROJECT_COMMAND_REFERENCE.md](./PROJECT_COMMAND_REFERENCE.md) §10).

### 2.5 Rehydrate from archive (if you want prior memory back)

```bash
cp archive/reset-YYYYMMDD-HHMM/historical_jobs.csv data/
cp archive/reset-YYYYMMDD-HHMM/jobs.csv data/
cp archive/reset-YYYYMMDD-HHMM/job_descriptions.csv data/
cp archive/reset-YYYYMMDD-HHMM/recruiter_crm.csv data/
cp archive/reset-YYYYMMDD-HHMM/linkedin_query_state.json data/.linkedin_query_state.json

python scripts/db_init.py
python scripts/import_csv_memory.py
python scripts/validate_sqlite_parity.py --mode import --fail-on-error
```

Skip import if you intend a **truly empty** DB and will bootstrap via acquisition only.

### 2.6 Smoke acquisition

```bash
export OPENAI_API_KEY="..."
# Optional: cap scrape/AI for smoke
LINKEDIN_MAX_RUNS=0 INSTAHYRE_MAX_RUNS=0 GREENHOUSE_MAX_RUNS=1 \
LEVER_MAX_RUNS=0 WEWORKREMOTELY_MAX_RUNS=0 \
python main.py
```

**Confirm in terminal:**

- `Pipeline historical index: SQLite`
- `SQLite write-primary: CSV persistence gated by SQLITE_EXPORT_* flags`
- `SQLITE DUAL-WRITE SUMMARY` → `enabled=1`, `success=1`

```bash
python scripts/validate_sqlite_parity.py --mode production --fail-on-error
```

Empty `historical_jobs.csv` / `recruiter_crm.csv` rows after smoke are **normal** under write-primary (SQLite is authoritative).

### 2.7 Refresh CSV exports and SOT check

With write-primary, on-disk CSV mirrors may be stale until export:

```bash
python scripts/export_csv_memory.py --all
python scripts/validate_sqlite_parity.py --mode source-of-truth --fail-on-error
```

### 2.8 Dashboard smoke

```bash
streamlit run dashboard/app.py
```

Default D8B: SQLite read/write on. Confirm sidebar indicates SQLite data source; edit a pipeline stage and CRM field; refresh — changes persist in DB.

**Dashboard verification checklist:**

1. Header shows **Last acquisition refresh** with a formatted timestamp.
2. KPI row: **Total Jobs**, **Latest Acquisition**, **Total Recruiters** — Total Jobs matches visible cohort (active + user-managed stages).
3. **Job Search Progression** section shows Discovery → Application → Outcomes stage cards.
4. Change sidebar **Location** or **Status** — Job Listings row count changes; Job Search Progression and Source Distribution **unchanged**.
5. Raise **Minimum score** — low/unscored `New` jobs disappear from table; Applied+ stages remain; progression counts unchanged.
6. **Showing X of Y** — X changes with filters; Y (dashboard cohort size) stays constant.
7. **Recommended Actions** — four panels in a **2×2 grid**: High Confidence, Apply Today, Apply This Week, Needs Review; queue counts **unchanged** when sidebar Location/Status filters change.
8. **Open Job** / **Applied ✓** / **Why?** — Open Job opens posting URL when link present (primary action); **Applied ✓** (Phase 3A.1) on High Confidence, Apply Today, and Apply This Week cards marks job Applied and removes it from apply queues on rerun; Needs Review cards show Open Job + Why? only; Why? popover shows full AI rationale.
9. Scrollable queue panels render (Streamlit ≥ 1.30); per-queue initial caps **8 / 10 / 12 / 10**; **Load More** adds 25 when `visible < total`; caption **Showing X of Y jobs** (caption left, Load More right); panel height shrinks for small queues (dynamic height, max 360px).
10. **Needs Review help icon** — info icon beside header shows tooltip (`14+ days old • Decide or clear`); **Job Listings** section title has HM enrichment help icon; sidebar **Source** filter and Source Distribution chart show human-readable source labels (LinkedIn, InstaHyre, etc.).
11. **Applied ✓ smoke (3A.1)** — With `SQLITE_DASHBOARD_WRITE=1`, click Applied ✓ on a High Confidence or Apply Today card; toast appears; job disappears from that queue; apply-queue count decrements; same job shows **Applied** in Job Listings. With writes off, Applied ✓ is disabled.

**Unit test smoke:**

```bash
python -m unittest \
  tests.test_dashboard_loaders \
  tests.test_dashboard_visibility \
  tests.test_dashboard_data_flow \
  tests.test_dashboard_funnel \
  tests.test_dashboard_funnel_workflow \
  tests.test_recommended_actions \
  tests.test_recommended_actions_applied \
  tests.test_display_text \
  tests.test_source_display \
  tests.test_dashboard_refresh_label \
  -v
```

### 2.9 Hiring Manager enrichment smoke (Phase 3B)

Requires `SQLITE_DASHBOARD_WRITE=1` (default under D8B). Confirm sidebar shows SQLite connected without write-disabled info banner on Job Listings.

1. Pick a job with **Hiring Manager** = `Not Specified` (or note current value).
2. Edit Hiring Manager to a valid name (e.g. recruiter full name); wait for save toast and rerun.
3. **Job Listings** row shows the new Hiring Manager.
4. **Recruiter CRM** — new or updated recruiter row; `source` = `job_editor` for newly created rows; `jobs_connected` ≥ 1.
5. Change Hiring Manager **A → B** on the same job — job row shows B; recruiter A remains in CRM with link history (append-only).
6. Clear to empty or `unknown` — job shows `Not Specified`; prior recruiter links **unchanged**.

**Unit test smoke:**

```bash
python -m unittest tests.test_recruiter_enrichment tests.test_dashboard_job_hiring_manager -v
```

---

## 3. Daily production workflow

Intended cadence: **twice-daily automated acquisition** (10:00 and 21:00 IST) + **manual** Streamlit dashboard review. Scheduling is implemented via macOS `launchd` — see [SCHEDULER_SETUP.md](./SCHEDULER_SETUP.md). Other schedulers can invoke the same wrapper script (`scripts/scheduling/run_scheduled_acquisition.sh`).

### 3.0 Scheduled automation (macOS)

**Cadence:** acquisition + parity at **10:00** and **21:00** IST daily; optional backup Sunday **23:00**. Overlapping runs skip when the file lock is held (`/tmp/ai-job-agent-acquisition.lock`).

**Install, plist labels, log paths, manual test, uninstall:** [SCHEDULER_SETUP.md](./SCHEDULER_SETUP.md) (canonical).

**Not scheduled:** Streamlit — use §3.4 manually.

Manual acquisition (§3.2–3.3) is equivalent when LaunchAgents are not installed.

### 3.1 Before acquisition

**Scheduled runs:** wrapper loads `.env` (including `OPENAI_API_KEY`), sets `LINKEDIN_MAX_RUNS=3`, and default `AI_CANDIDATE_PROFILE_PATH`; see [SCHEDULER_SETUP.md](./SCHEDULER_SETUP.md).

**Manual runs:**

- Activate venv: `source venv/bin/activate`
- `export OPENAI_API_KEY="..."`
- LinkedIn cap: `LINKEDIN_MAX_RUNS=3` (or omit for code default of 5)
- Edit scoring identity if needed: [`config/profiles/ai_candidate_profile.example.md`](../config/profiles/ai_candidate_profile.example.md) (see [config/profiles/README.md](../config/profiles/README.md))
- Optional: `DEBUG_LIMIT=300` (default in code; override via env)
- LinkedIn Top Applicant anchor: `unset LINKEDIN_QUALIFICATION_LANDING_URL` so [`config/linkedin_queries.json`](../config/linkedin_queries.json) `top_applicants_anchor.landing_url` is used (refresh that URL when the feed drifts)

### 3.2 Run acquisition (default flags)

```bash
python main.py
```

**Do not** export `SQLITE_ENABLED=1` etc. — defaults are already on.

**Confirm:**

- Pipeline SQLite read lines
- Write-primary banner (if enabled)
- Dual-write `success=1`
- Candidate profile path logged at AI stage
- When Instahyre enabled (`INSTAHYRE_MAX_RUNS` ≠ 0): `🟣 INSTAHYRE INTERESTED SYNC SUMMARY` — note `protected_count` (stages preserved), `not_required_evals_written`, `sync_run_id`

### 3.3 Post-run validation

Scheduled runs already run this step in the acquisition wrapper. For **manual** runs:

```bash
python scripts/validate_sqlite_parity.py --mode production --fail-on-error
```

Validates SQLite health and D2 `jobs.csv` cohort parity. Does **not** require populated historical/CRM CSV mirrors (those are optional exports).

Under default flags (`SQLITE_EXPORT_HISTORICAL_CSV=0`), **stale rows** in `historical_jobs.csv` that are not in SQLite produce a **warning only**, not a failure. Strict historical CSV↔DB key parity applies when `SQLITE_EXPORT_HISTORICAL_CSV=1` or when using `--mode source-of-truth` after `export_csv_memory.py`.

Legacy strict CSV mirror check (optional): `python scripts/validate_sqlite_parity.py --mode csv-mirror-sync` or deprecated `validate_dual_write_parity.py` (after `export_csv_memory.py --all`).

### 3.4 Dashboard review

```bash
streamlit run dashboard/app.py
```

Review ranked jobs, historical memory, recruiter CRM, pipeline stages, Job Search Progression, four-queue Recommended Actions (Applied ✓ on apply queues), and source distribution. Use the dashboard verification checklist in §2.8.

**Interested sync + routing unit tests** (optional, after Instahyre runs):

```bash
python -m unittest \
  tests.test_instahyre_interested_sync \
  tests.test_pipeline_user_managed_routing \
  -v
```

### 3.5 Periodic backup (weekly or before risky changes)

Manual commands:

```bash
./scripts/archive_state.sh
python scripts/export_csv_memory.py --all
python scripts/validate_sqlite_parity.py --mode source-of-truth --fail-on-error
```

Optional automation: `scripts/scheduling/run_scheduled_backup.sh` via LaunchAgent (Sunday 23:00) — [SCHEDULER_SETUP.md](./SCHEDULER_SETUP.md).

---

## 4. Emergency rollback

| Level | Action |
|-------|--------|
| **L0** | `SQLITE_ENABLED=0 python main.py` and same for Streamlit — CSV-only path |
| **L1** | Disable one flag, e.g. `SQLITE_PIPELINE_READ=0`, to isolate a subsystem |
| **L2** | Git revert D8B default-flag commit |
| **L3** | Archive → bootstrap reset → import from archive |

Rollback levels aligned with [D8B_PROMOTION_SIGNOFF.md](./D8B_PROMOTION_SIGNOFF.md) evidence archive; live procedure: this section + §2.

---

## 5. AI scoring configuration

| Item | Location | Notes |
|------|----------|-------|
| Candidate profile | `config/profiles/ai_candidate_profile.example.md` | Preferences and signals only; not the scorer instruction block |
| Profile override | `AI_CANDIDATE_PROFILE_PATH` | Absolute or repo-relative path |
| Scoring rules / prompt | `src/agent/ai_batch_scorer.py` | Unchanged by profile file; edit only when changing evaluation criteria |
| `DEBUG_LIMIT` | `src/agent/ai_runtime_config.py` or env | Default **300** jobs scored per run |
| `BATCH_SIZE` | `src/agent/ai_runtime_config.py` or env | Default **15**; override e.g. `BATCH_SIZE=20` |
| Description cap | `AI_DESCRIPTION_MAX_CHARS` in `ai_batch_scorer.py` | Default **3000** chars per job in prompt |

---

## 6. Evidence and sign-off logs

Read-only references for promotion validation:

| Artifact | Path |
|----------|------|
| D8A readiness | `logs/d8a-promotion-readiness-20260603.md` |
| D8B post-flip run | `logs/d8b-post-flip-run-20260603-134740.log` |
| D8B SOT validator | `logs/d8b-post-flip-sot-20260603-134753.log` |
| Flag remediation | `logs/d8b-remediation-post-flip-run-20260603-142154.log` |
| D8B sign-off | [D8B_PROMOTION_SIGNOFF.md](./D8B_PROMOTION_SIGNOFF.md) |
