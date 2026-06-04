# Production Operations

Step-by-step operator guide for **daily use** and **pre-production reset** after D8B SQLite promotion.

**System overview (milestones, architecture, roadmap):** [PRODUCT_STATUS_SUMMARY.md](./PRODUCT_STATUS_SUMMARY.md)  
**Command catalog and flags:** [PROJECT_COMMAND_REFERENCE.md](./PROJECT_COMMAND_REFERENCE.md) §10b  
**Migration history:** [SQLITE_IMPLEMENTATION_PLAN.md](./SQLITE_IMPLEMENTATION_PLAN.md)

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

Optional: `python -m unittest tests.test_dashboard_loaders -q`

---

## 3. Daily production workflow

Intended cadence: **scheduled or twice-daily** acquisition + dashboard review (configure scheduling outside the repo, e.g. cron or LaunchAgent).

### 3.1 Before acquisition

- Activate venv: `source venv/bin/activate`
- `export OPENAI_API_KEY="..."`
- Edit scoring identity if needed: [`config/profiles/ai_candidate_profile.example.md`](../config/profiles/ai_candidate_profile.example.md) or your path via `AI_CANDIDATE_PROFILE_PATH` (see [config/profiles/README.md](../config/profiles/README.md))
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

### 3.3 Post-run validation

```bash
python scripts/validate_sqlite_parity.py --mode production --fail-on-error
```

Validates SQLite health and D2 `jobs.csv` cohort parity. Does **not** require populated historical/CRM CSV mirrors (those are optional exports).

Legacy strict CSV mirror check (optional): `python scripts/validate_sqlite_parity.py --mode csv-mirror-sync` or deprecated `validate_dual_write_parity.py` (after `export_csv_memory.py --all`).

### 3.4 Dashboard review

```bash
streamlit run dashboard/app.py
```

Review ranked jobs, historical memory, recruiter CRM, pipeline stages.

### 3.5 Periodic backup (weekly or before risky changes)

```bash
./scripts/archive_state.sh
python scripts/export_csv_memory.py --all
python scripts/validate_sqlite_parity.py --mode source-of-truth --fail-on-error
```

---

## 4. Emergency rollback

| Level | Action |
|-------|--------|
| **L0** | `SQLITE_ENABLED=0 python main.py` and same for Streamlit — CSV-only path |
| **L1** | Disable one flag, e.g. `SQLITE_PIPELINE_READ=0`, to isolate a subsystem |
| **L2** | Git revert D8B default-flag commit |
| **L3** | Archive → bootstrap reset → import from archive |

See [SQLITE_IMPLEMENTATION_PLAN.md](./SQLITE_IMPLEMENTATION_PLAN.md) §15 rollback procedures.

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

## 6. Clone setup pointer

Fresh public clones: [CLONE_SETUP.md](./CLONE_SETUP.md). D8A/D8B promotion validation was completed during migration; detailed operator logs are not part of this repository.
