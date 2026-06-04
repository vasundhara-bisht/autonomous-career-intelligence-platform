# Project Command Reference

PM-friendly cheat sheet for running, debugging, and operating **ai-job-agent**.  
All commands assume you are in the **repository root** unless noted otherwise.

**Runtime data lives in:** `data/` (CSVs, auth JSON, LinkedIn query state)  
**Config catalogs live in:** `config/` (no secrets)

---

## Quick safety labels

| Label | Meaning |
|-------|---------|
| **Safe** | Read-only or normal daily use |
| **Lightweight** | Fast check; limited scraping or no browser |
| **Heavy** | Full scrape + AI; costs time and API credits |
| **Destructive** | Erases or overwrites live state |

---

## 1. Environment setup

| Command | What it does | When to use | Safety |
|---------|--------------|-------------|--------|
| `python -m venv venv` | Creates a local Python environment | First-time setup | Safe |
| `source venv/bin/activate` | Activates venv (macOS/Linux) | Every new terminal session | Safe |
| `venv\Scripts\activate` | Activates venv (Windows) | Every new terminal session | Safe |
| `pip install -r requirements.txt` | Installs dependencies **and** editable package (`-e .`) | After clone or dependency changes | Safe |
| `pip install -e .` | Installs project so `paths`, `agent` import from anywhere | If Streamlit shows `No module named 'paths'` | Safe |
| `playwright install chromium` | Downloads browser for LinkedIn/Instahyre scrapers | Once per machine/venv | Safe |

### Required secret (pipeline AI scoring)

| Variable / file | What it does | When to use | Safety |
|-----------------|--------------|-------------|--------|
| `export OPENAI_API_KEY="..."` | Powers AI batch scoring | Before any run that reaches AI stage | Safe (keep private) |
| `data/linkedin_auth.json` | Saved LinkedIn browser session | Created by LinkedIn scraper login flow | Safe locally; never commit |
| `data/instahyre_auth.json` | Saved Instahyre browser session | Created by Instahyre scraper login flow | Safe locally; never commit |

### Optional data location override

| Variable | Default | What it does | When to use | Safety |
|----------|---------|--------------|-------------|--------|
| `AI_JOB_AGENT_DATA_DIR` | `<repo>/data` | Points all CSV/auth paths to a custom folder | Multiple clones, external disk | Safe |

---

## 2. Main pipeline runs

Entry point is always:

```bash
python main.py
```

Run from repo root with venv active.

| Command pattern | What it does | When to use | Safety |
|-----------------|--------------|-------------|--------|
| `python main.py` | Full pipeline: scrape → filter → dedup → descriptions → AI → export | Normal daily refresh | **Heavy** |
| `export OPENAI_API_KEY="..." && python main.py` | Same, with AI enabled | Production-style run | **Heavy** |
| `LINKEDIN_MAX_RUNS=0 INSTAHYRE_MAX_RUNS=1 python main.py` | Skip LinkedIn; run Instahyre (+ other sources per their defaults) | Instahyre-focused validation | Heavy |
| `LINKEDIN_MAX_RUNS=0 INSTAHYRE_MAX_RUNS=0 GREENHOUSE_MAX_RUNS=0 LEVER_MAX_RUNS=0 WEWORKREMOTELY_MAX_RUNS=0 python main.py` | Skips all acquisition (downstream stages still run on empty/new input) | Fast import/path smoke test only | Lightweight |
| `INSTAHYRE_MAX_RUNS=0 WEWORKREMOTELY_MAX_RUNS=0 LEVER_MAX_RUNS=0 GREENHOUSE_MAX_RUNS=0 LINKEDIN_MAX_RUNS=1 python main.py` | LinkedIn-only acquisition test | LinkedIn orchestration validation | Heavy |
| `LINKEDIN_MAX_RUNS=0 INSTAHYRE_MAX_RUNS=1 GREENHOUSE_MAX_RUNS=0 LEVER_MAX_RUNS=0 WEWORKREMOTELY_MAX_RUNS=0 python main.py` | Instahyre-only (no GH/Lever/WWR/LinkedIn) | Targeted Instahyre run | Heavy |

On startup, the pipeline may print migrated files if old root-level CSVs are moved into `data/`.

---

## 3. Source throttling (`*_MAX_RUNS`)

Controlled in `scraper/acquisition_gate.py` and `src/agent/main.py`.

| Variable | Default if unset | `0` | Positive number `N` | Invalid value |
|----------|------------------|-----|------------------------|---------------|
| `LINKEDIN_MAX_RUNS` | 5 queries | Disables LinkedIn | Caps orchestrated queries to N | Falls back to default |
| `INSTAHYRE_MAX_RUNS` | 2 feeds | Disables Instahyre | Caps feeds to N | Falls back to default |
| `GREENHOUSE_MAX_RUNS` | 1 run | Disables Greenhouse | Caps to N | Falls back to default |
| `LEVER_MAX_RUNS` | 1 run | Disables Lever | Caps to N | Falls back to default |
| `WEWORKREMOTELY_MAX_RUNS` | 1 run | Disables WeWorkRemotely | Caps to N | Falls back to default |

**Tip:** Set any source to `0` to skip it entirely. Leave unset to use the default cap.

---

## 4. LinkedIn-specific controls

| Variable | Default | What it does | When to use | Safety |
|----------|---------|--------------|-------------|--------|
| `LINKEDIN_QUERY_IDS` | (all eligible) | Comma-separated query IDs from `config/linkedin_queries.json` | Run only specific searches | Heavy |
| `LINKEDIN_LEGACY_SINGLE_QUERY=1` | off | Uses old single-URL scrape instead of orchestrator | Legacy/debug comparison | Heavy |
| `LINKEDIN_PRIORITY_ANCHOR` | on (config) | Set to `0`/`false`/`off` to skip priority anchor query | Narrow session behavior | Heavy |
| `LINKEDIN_PRIORITY_ANCHOR_ID` | from config | Forces anchor query ID | Debug anchor selection | Heavy |
| `LINKEDIN_MAX_NEXT_PAGES` | 5 | Max pagination steps per search | Limit LinkedIn volume | Heavy |
| `LINKEDIN_MAX_SHOW_MORE_CLICKS` | 3 | Max "show more" expansions | Limit list growth | Heavy |
| `LINKEDIN_SHOW_MORE_NO_GROWTH_STOP` | 2 | Stop after N no-growth show-more attempts | Stability tuning | Heavy |
| `LINKEDIN_RESET_ABORT_THRESHOLD` | 2 | Abort after repeated list resets | Stability tuning | Heavy |
| `LINKEDIN_PLAYWRIGHT_TRACE=1` | off | Records Playwright trace zip | Deep LinkedIn debugging | Heavy |
| `LINKEDIN_PLAYWRIGHT_TRACE_PATH` | `linkedin_playwright_trace.zip` | Output path for trace | With trace enabled | Heavy |
| `LINKEDIN_QUALIFICATION_LANDING_URL` | from `config/linkedin_queries.json` | Overrides the priority anchor How You Fit / Top Applicant URL without editing JSON | Refresh personalized feed URL quickly | Heavy |
| `LINKEDIN_BROAD_PM_LANDING_URL` | from `config/linkedin_queries.json` | Overrides `broad_pm_easy_apply_7d` search-results URL without editing JSON | Refresh broad PM Easy Apply feed URL | Heavy |
| `LINKEDIN_PRIORITY_FOLLOWUP` | on (config) | Set to `0`/`false`/`off` to skip priority follow-up query after anchor | Single-query anchor-only sessions | Heavy |

LinkedIn scraper opens a **visible browser** (`headless=False`) for login/session use.

### Priority anchor: Top Applicant / How You Fit

The default priority anchor (`top_applicants_anchor`) uses `url_mode: qualification_landing` — a full LinkedIn **search-results** URL with `showHowYouFit=HOW_YOU_FIT` and `origin=QUALIFICATION_LANDING`, not the old `f_JIYN` low-applicant search approximation.

**Refresh the landing URL** when fit drifts (jobs close, feed changes):

1. In LinkedIn (logged in), open your Top Applicant / How You Fit PM feed and copy the browser URL.
2. Update `landing_url` on query `top_applicants_anchor` in `config/linkedin_queries.json`, **or** set `LINKEDIN_QUALIFICATION_LANDING_URL` for a one-off run.
3. Before production runs using the JSON URL, **`unset LINKEDIN_QUALIFICATION_LANDING_URL`** so the env does not override config.

Portfolio placeholder `landing_url` on `top_applicants_anchor`: `currentJobId=PLACEHOLDER_JOB_001`, `originToLandingJobPostings=PLACEHOLDER_JOB_001,PLACEHOLDER_JOB_002,PLACEHOLDER_JOB_003` (see `config/linkedin_queries.json`). Replace with your live LinkedIn URL locally.

**LinkedIn-only anchor validation** (requires `data/linkedin_auth.json`):

```bash
INSTAHYRE_MAX_RUNS=0 GREENHOUSE_MAX_RUNS=0 LEVER_MAX_RUNS=0 WEWORKREMOTELY_MAX_RUNS=0 \
LINKEDIN_MAX_RUNS=1 DEBUG_LINKEDIN=1 python main.py
```

Expect: first query `Top Applicant / How You Fit PM`, `linkedin_filter_profile=qualification_landing`, jobs collected &gt; 0, final URL contains `search-results` or `showHowYouFit`.

### Priority follow-up: Broad PM Easy Apply 7d

Second query (`broad_pm_easy_apply_7d`) runs immediately after the anchor when `defaults.priority_followup.enabled` is true and the session has orchestrated budget (`LINKEDIN_MAX_RUNS` ≥ 2 with anchor counting toward max).

- **Query id:** `broad_pm_easy_apply_7d`
- **URL mode:** `search_results_landing` (PM keywords + Easy Apply + 7d via `f_TPR=r604800`, `f_AL=true`)
- **Metadata:** `linkedin_filter_profile=easy_apply_7d`

**Refresh the broad PM landing URL** from your LinkedIn job search (Easy Apply + Past week), then update `landing_url` on `broad_pm_easy_apply_7d` or set `LINKEDIN_BROAD_PM_LANDING_URL`.

**Two-query validation** (anchor + broad PM; requires `data/linkedin_auth.json`):

```bash
INSTAHYRE_MAX_RUNS=0 GREENHOUSE_MAX_RUNS=0 LEVER_MAX_RUNS=0 WEWORKREMOTELY_MAX_RUNS=0 \
LINKEDIN_MAX_RUNS=2 DEBUG_LINKEDIN=1 python main.py
```

Expect: `[PRIORITY_ANCHOR] top_applicants_anchor`, then `[PRIORITY_FOLLOWUP] broad_pm_easy_apply_7d`, both with jobs collected &gt; 0.

**Note:** `LINKEDIN_MAX_RUNS=1` runs only the anchor (by design). To test Query 2 alone: `LINKEDIN_MAX_RUNS=1 LINKEDIN_PRIORITY_ANCHOR=0 LINKEDIN_QUERY_IDS=broad_pm_easy_apply_7d`.

---

## 5. Instahyre-specific controls

| Variable | Default | What it does | When to use | Safety |
|----------|---------|--------------|-------------|--------|
| `INSTAHYRE_FEED_IDS` | (catalog order) | Comma-separated feed IDs from `config/instahyre_feeds.json` | Run specific feeds only | Heavy |
| `INSTAHYRE_QUERY_IDS` | — | Alias for `INSTAHYRE_FEED_IDS` if feed IDs unset | Same as above | Heavy |
| `INSTAHYRE_MAX_JOBS_PER_FEED` | **10000** (effectively uncapped) | Max detail extractions per feed; set lower to cap volume | Pagination runs typically need no override | Heavy |
| `INSTAHYRE_SCROLL_MAX_CYCLES` | **18** when unset (paginated feeds); 12 for legacy | Scroll fallback / legacy feeds only | Volume/stability tuning | Heavy |
| `INSTAHYRE_STABLE_ROUNDS` | **5** when unset (paginated feeds); 3 for legacy | Scroll fallback / legacy | DOM load tuning | Heavy |
| `INSTAHYRE_LIST_WAIT_MS` | **55000** when unset (paginated feeds); 45000 legacy | Wait for list (ms) | Slow network tuning | Heavy |
| `INSTAHYRE_POST_SCROLL_WAIT_MS` | **2000** when unset (paginated feeds); 1200 legacy | Post-scroll wait (scroll path) | Heavy |
| `INSTAHYRE_MATCHING_MIN_SCROLL_CYCLES` | 4 | Feed 1 scroll fallback only: minimum scroll cycles before stable exit | Avoid premature stop | Heavy |
| `INSTAHYRE_MATCHING_INITIAL_SETTLE_MS` | 1800 | Feed 1: pause after initial list wait | List hydration | Heavy |
| `INSTAHYRE_MAX_PAGES` | **5** (Feed 1) | Feed 1 pagination: max list pages to traverse | Cap pagination depth | Heavy |
| `INSTAHYRE_PAGE_MIN_NEW_RATIO` | **0.15** (Feed 1) | Stop when a page adds fewer than this fraction of new job IDs | Saturation tuning | Heavy |
| `INSTAHYRE_PAGE_TRANSITION_WAIT_MS` | 10000 | Max wait for active page / first job change after Next click | Slow Angular pages | Heavy |
| `INSTAHYRE_PAGE_SETTLE_MS` | 1500 | Pause after a successful page transition before harvest | List hydration | Heavy |
| `INSTAHYRE_MATCHING_SCROLL_FALLBACK` | 0 | Set `1` to use legacy scroll discovery instead of pagination on Feed 1 | Scroll A/B or regression | Heavy |

Feed 1 (`matching_personalized`) and Feed 2 (`pm_curated_search` → `/search-jobs`) default to **pagination traversal** (harvest all pages, then detail extraction). Debug metrics: `pages_traversed`, `cards_per_page`, `cumulative_unique_job_ids`, `pagination_stop_reason`, `final_unique_instahyre_jobs`, `page_traversal_details`.

With `INSTAHYRE_MATCHING_SCROLL_FALLBACK=1`, Feed 1 uses the scroll strategy chain (`container_scroll` → … → `document_wheel_last_resort`). Metrics: `strategy_fallback_chains`, `ineffective_scroll_cycles`, `scroll_strategy_used`.

**Isolated Feed 1 pagination validation:**

```bash
DEBUG_INSTAHYRE=true \
LINKEDIN_MAX_RUNS=0 GREENHOUSE_MAX_RUNS=0 LEVER_MAX_RUNS=0 WEWORKREMOTELY_MAX_RUNS=0 \
INSTAHYRE_MAX_RUNS=1 INSTAHYRE_FEED_IDS=matching_personalized \
INSTAHYRE_MAX_PAGES=5 \
python main.py

python -m unittest tests.test_instahyre_discovery tests.test_historical_persistence -v
```

Success indicators: `traversal_mode=pagination`, `pages_traversed >= 2`, opportunity cards / unique IDs **> 30**, `pagination_stop_reason` in (`no_next`, `max_pages`, `saturation`) — not `transition_failed` on page 1.

**Isolated Feed 2 (search-jobs) validation:**

```bash
DEBUG_INSTAHYRE=true \
LINKEDIN_MAX_RUNS=0 GREENHOUSE_MAX_RUNS=0 LEVER_MAX_RUNS=0 WEWORKREMOTELY_MAX_RUNS=0 \
INSTAHYRE_MAX_RUNS=1 INSTAHYRE_FEED_IDS=pm_curated_search \
INSTAHYRE_MAX_PAGES=5 \
python main.py
```

Success indicators: `feed_id=pm_curated_search`, URL contains `/search-jobs`, `traversal_mode=pagination`, `pages_traversed >= 1`, detail extraction after pagination completes.

**Pagination DOM probe (read-only):**

```bash
python scripts/instahyre_dom_probe.py
```

---

## 6. Debug and logging flags

Truthy values for most debug flags: `1`, `true`, `yes`, `on` (case-insensitive).

| Variable | What it does | When to use | Safety |
|----------|--------------|-------------|--------|
| `DEBUG_STAGE1=true` | Logs each job through Stage 1 (title/location filter) | Understand rejections | Lightweight (verbose) |
| `DEBUG_LINKEDIN=true` | LinkedIn traversal diagnostics, session plan, pauses | LinkedIn scrape issues | Heavy + verbose |
| `LINKEDIN_VERBOSE_DIAG=true` | Same as `DEBUG_LINKEDIN` (legacy alias) | Same | Heavy + verbose |
| `DEBUG_INSTAHYRE=true` | Instahyre feed metrics, rejections, tracebacks | Instahyre scrape issues | Heavy + verbose |
| `INSTAHYRE_DEBUG_DOM=true` | Extra DOM debug (also if `DEBUG_INSTAHYRE`) | Instahyre page structure issues | Heavy + verbose |
| `DEBUG_IDENTITY=true` | Extra identity funnel + dedup hit details in production health | Identity/memory debugging | Lightweight (extra logs) |
| `DEBUG_AI=true` | OpenAI request/response debug, parse errors | AI scoring failures | Heavy (API calls) |

### Reading pipeline logs (standard run)

After identity routing, look for:

- `Historical lookup stats (routing)` — V2 hits vs legacy fallback during historical lookup
- `Intake (raw scraped jobs) unresolved identity` — unresolved tier mix on all scraped jobs
- `Brand-new description pass` / `Needs-AI-only cache hydration` — separate description pools (not one combined “reused” total)
- `AI queue cap (DEBUG_LIMIT)` — candidates vs capped vs skipped; cap skip note only when skipped > 0
- `Export composition (this session)` — fully_processed + AI-scored counts before final merge
- `PIPELINE METRICS` — stage funnel counts; `PIPELINE SUMMARY` — routing + AI only (points to METRICS)
- `Scope: intake-wide` / `Scope: export cohort only` — clarifies routing lookup vs export health V2 rates
- `PRODUCTION IDENTITY HEALTH` — export-cohort unresolved count and by-source breakdown

### Full debug run (from README)

```bash
DEBUG_STAGE1=true DEBUG_LINKEDIN=true DEBUG_INSTAHYRE=true \
DEBUG_IDENTITY=true DEBUG_AI=true python main.py
```

| Safety | **Heavy** — very noisy; use on small `*_MAX_RUNS` caps |

### Always-on vs gated logging

| Output | Gated? |
|--------|--------|
| Stage 1 summary (counts, buckets, by source) | Always on |
| Dedup progress + summary | Always on |
| Duplicate hit details (V2 / exact / fuzzy) | Always on when a duplicate is removed |
| AI batch progress (`Batch N Complete`) | Always on |
| Job Identity Health / Production Identity Health | Always on (summary) |
| Identity funnel tables | `DEBUG_IDENTITY=true` only |
| LinkedIn session plan | `DEBUG_LINKEDIN=true` only |

**Note:** There is **no** separate dedup debug flag. Dedup logging was improved to always show check steps and a clear "no duplicates" message.

---

## 7. Code-level tuning (not environment variables)

Most pipeline tuning lives in `src/agent/main.py` (code edit). Profile and AI cap also support env overrides.

| Setting | Location | Default | What it does |
|---------|----------|---------|--------------|
| `DEBUG_LIMIT` | `agent/ai_runtime_config.py` | `300` | Max jobs sent to AI scoring per run; override: `export DEBUG_LIMIT=50` |
| `BATCH_SIZE` | `agent/ai_runtime_config.py` | `15` | Jobs per OpenAI batch; override: `BATCH_SIZE=20 python main.py` |
| **AI candidate profile** | [`config/profiles/ai_candidate_profile.example.md`](../config/profiles/ai_candidate_profile.example.md) | Loaded by `load_candidate_profile()`; override: `AI_CANDIDATE_PROFILE_PATH` — see [config/profiles/README.md](../config/profiles/README.md) |

Scoring rules and JSON output format stay in [`src/agent/ai_batch_scorer.py`](../src/agent/ai_batch_scorer.py) (not in the profile file). Stage-1 filtering does **not** use the profile text.

| Variable | Default | What it does | When to use | Safety |
|----------|---------|--------------|-------------|--------|
| `HISTORICAL_V2_UPSERT` | `1` (on) | V2-assisted historical upsert when legacy key misses | Turn off only for legacy experiments | Safe |

---

## 8. Streamlit dashboard

| Command | What it does | When to use | Safety |
|---------|--------------|-------------|--------|
| `streamlit run dashboard/app.py` | Starts interactive dashboard (D8B: SQLite read/write by default) | Review ranked jobs, CRM, history | Safe |
| `streamlit run dashboard/app.py --server.port 8502` | Same on custom port | Port conflict | Safe |

**Prerequisite:** `pip install -r requirements.txt` (includes editable install).

### Default path (D8B)

No `SQLITE_*` exports required:

```bash
streamlit run dashboard/app.py
```

| Concern | Default source |
|---------|----------------|
| Current jobs | `current_jobs_view` |
| Historical jobs | `historical_jobs_view` |
| Recruiter CRM | `active_recruiters_view` |
| Pipeline stage / notes | `user_job_state` (writes when `SQLITE_DASHBOARD_WRITE=1`, default on) |
| Recruiter edits | `recruiters` table |

Sidebar should reflect SQLite-backed data. After editing a pipeline stage or recruiter field, refresh — changes persist in the DB.

### CSV fallback (emergency or legacy)

```bash
SQLITE_ENABLED=0 streamlit run dashboard/app.py
# or disable reads only:
SQLITE_READ=0 streamlit run dashboard/app.py
```

Reads fall back to `data/jobs.csv`, `data/historical_jobs.csv`, `data/recruiter_crm.csv`. Refresh on-disk CSVs via `python scripts/export_csv_memory.py --all` if DB was authoritative.

**First machine / after drift:** `python scripts/db_init.py`, optional `import_csv_memory.py`, then `pytest tests/test_dashboard_loaders.py -q`.

**Disable writes only:** `SQLITE_DASHBOARD_WRITE=0` (display from DB; stage edits may not persist to SQLite).

---

## 9. Validation and testing

| Command | What it does | When to use | Safety |
|---------|--------------|-------------|--------|
| `python3 scripts/validate_bootstrap.py` | Checks `data/` CSV schemas and historical V2 fill rate | After reset + one `main.py` run | Safe |
| `python3 scripts/validate_bootstrap.py --min-historical-rows 10` | Stricter row count check | Fuller bootstrap validation | Safe |
| `python3 scripts/validate_bootstrap.py --min-v2-fill-rate 0.99` | Stricter V2 coverage | Identity hardening check | Safe |
| `python3 scripts/validate_bootstrap.py --log path/to/log.txt` | Optional log grep for V2 merge authority | Deep validation | Safe |
| `python3 scripts/instahyre_dom_probe.py` | Read-only Instahyre DOM probe (JSON to terminal) | Instahyre page broken / zero cards | Lightweight (needs auth) |

### Lightweight module checks (no full scrape)

```bash
# Imports + paths
python -c "import paths; import agent.main; print(paths.jobs_csv())"

# Dedup logging only
python -c "from agent.dedup_engine import deduplicate_jobs; deduplicate_jobs([...])"
```

| Safety | **Safe** / **Lightweight** |

---

## 10. Helper scripts (`scripts/`)

| Script | Command | What it does | When to use | Safety |
|--------|---------|--------------|-------------|--------|
| Archive state | `./scripts/archive_state.sh` | Copies `data/` runtime files to `archive/reset-YYYYMMDD-HHMM/` + `MANIFEST.json` | **Before** any reset | Safe |
| Archive (compress) | `./scripts/archive_state.sh --compress` | Same + `.tar.gz` | Backup retention | Safe |
| Reset state | `./scripts/reset_state.sh --archive-id reset-YYYYMMDD-HHMM --profile crm-preserving` | Wipes selected runtime CSVs/JSON to empty schemas by profile | Clean slate after archive | **Destructive** |
| Reset dry-run | `./scripts/reset_state.sh --archive-id <id> --profile bootstrap --dry-run` | Prints reset plan, schemas, row counts, and preserved files; no writes | Preview reset | Safe |
| Reset (no prompt) | `... --no-confirm` | Skips `RESET` confirmation | Automation only | **Destructive** |
| Reset (templates) | `... --use-template-fallback` | Uses `scripts/templates/*.header.csv` instead of live schema derivation | Fallback if Python schema import fails | **Destructive** |
| Reset auth | `... --reset-auth` | Also resets LinkedIn/Instahyre browser storage states | Rare login/session testing only | **Destructive** |

### Reset profiles

| Profile | Clears | Preserves |
|---------|--------|-----------|
| `bootstrap` | `historical_jobs.csv`, `jobs.csv`, `job_descriptions.csv`, `.linkedin_query_state.json`, `recruiter_crm.csv` | auth, config, source; SQLite product tables when `SQLITE_ENABLED=1` |
| `acquisition` | `jobs.csv`, `.linkedin_query_state.json` | historical memory, descriptions, CRM, auth; SQLite run-scoped tables |
| `crm-preserving` | `historical_jobs.csv`, `jobs.csv`, `job_descriptions.csv`, `.linkedin_query_state.json` | CRM, auth, config, source; SQLite jobs domain (not recruiters) |
| `full` | same as `bootstrap` | auth by default (add `--reset-auth` only intentionally) |

### Recommended reset workflow

1. `./scripts/archive_state.sh` → note `RESET_ID=reset-...`
2. Stop `main.py` and Streamlit if running
3. `./scripts/reset_state.sh --archive-id reset-... --profile bootstrap --dry-run`
4. `./scripts/reset_state.sh --archive-id reset-... --profile bootstrap`
5. `python main.py` (bootstrap run)
6. `python3 scripts/validate_bootstrap.py`

### Identity / V2 migration helpers

| Script | Command | What it does | Safety |
|--------|---------|--------------|--------|
| Identity inventory | `python3 scripts/identity_inventory.py` | Read-only V2/legacy fill rates; flags description rows not in historical (SQLite prep) | Safe — see §10b |
| Description identity migrate | `python3 scripts/migrate_identity_descriptions.py` | Dry-run dedupe/backfill of `job_descriptions.csv` by V2 | Safe (dry-run) |
| Description migrate apply | `python3 scripts/migrate_identity_descriptions.py --apply` | Writes reindexed descriptions | **Destructive** (archive first) |

Set `DEBUG_IDENTITY=true` on a pipeline run for per-job description reuse logs (`reuse_via=v2` / `legacy`).

---

## 10b. SQLite product memory (source of truth) {#sqlite-product-memory-source-of-truth}

**System status (milestones, limitations, roadmap):** [PRODUCT_STATUS_SUMMARY.md](./PRODUCT_STATUS_SUMMARY.md)  
**Daily ops and pre-reset:** [PRODUCTION_OPERATIONS.md](./PRODUCTION_OPERATIONS.md)

**Canonical operator reference for SQLite.** As of D8B (2026-06-03), **`data/ai_job_agent.db` is the default source of truth** for product memory. CSV files under `data/` are optional exports for backup, handoff, and recovery — not the daily read path.

### Default path (D8B) — no env exports

```bash
export OPENAI_API_KEY="..."
python main.py
python scripts/validate_sqlite_parity.py --mode production --fail-on-error
streamlit run dashboard/app.py
```

Confirm terminal: `Pipeline historical index: SQLite`, `SQLite write-primary: CSV persistence gated`, `SQLITE DUAL-WRITE SUMMARY` with `enabled=1` / `success=1`.

**Emergency CSV-only:** `SQLITE_ENABLED=0 python main.py` (and dashboard with same) restores legacy CSV operation without reverting code.

**No env exports required:** D8B SOT flags default on in `src/db/config.py` via `sqlite_flag()` — you do not need to export `SQLITE_*` variables for normal acquisition or dashboard use. Set individual flags to `0` only to disable specific subsystems.

**Database file:** `data/ai_job_agent.db` (override path: `AI_JOB_AGENT_DB_PATH`)

### Daily production ritual

After each acquisition run:

1. `python scripts/validate_sqlite_parity.py --mode production --fail-on-error`
2. Review dashboard (`streamlit run dashboard/app.py`)
3. Weekly or before backup/SOT check: `python scripts/export_csv_memory.py --all` then `python scripts/validate_sqlite_parity.py --mode source-of-truth --fail-on-error`

With write-primary, empty historical/CRM CSV mirrors are **normal** after step 1 (production mode). Step 3 validates exported backups against SQLite.

### Pre-production reset ritual

Full sequence: [PRODUCTION_OPERATIONS.md](./PRODUCTION_OPERATIONS.md) §2 (archive → bootstrap reset → optional import from archive → smoke `main.py` → export + SOT PASS → dashboard smoke).

### Feature flags (pipeline)

Defaults reflect D8B promotion (`src/db/config.py`). Set env var to `0` to disable individual flags.

| Variable | Default | Meaning |
|----------|---------|---------|
| `SQLITE_ENABLED` | `1` (D8B) | Master switch for any SQLite access; **`0` = emergency CSV-only** |
| `SQLITE_DUAL_WRITE` | `1` (D8B) | Write persistence cohort to SQLite at end of `main.py` |
| `SQLITE_READ` | `1` (D8B) | Dashboard display reads from SQLite when `SQLITE_ENABLED=1` |
| `SQLITE_EXPORT_FROM_DB` | `1` when `SQLITE_ENABLED=1` (D2) | Generate `jobs.csv` from `current_jobs_view`; falls back to legacy export on hard parity failure |
| `SQLITE_METADATA_HARD_PARITY` | `0` (D3) | `1` = metadata coverage gaps fail DB export parity (default WARN-only) |
| `SQLITE_PIPELINE_READ` | `1` (D8B) | Pipeline reads historical index + description cache from SQLite; CSV fallback on error |
| `SQLITE_QUERY_STATE_READ` | `0` (D4 opt-in) | LinkedIn orchestrator reads `query_cooldown_state`; JSON file remains write-through mirror |
| `SQLITE_WRITE_PRIMARY` | `1` (D8B) | SQLite dual-write authoritative; CSV persistence writes gated by `SQLITE_EXPORT_*` |
| `SQLITE_EXPORT_JOBS_CSV` | `1` (D8B) | Export `jobs.csv` via D2 DB path when write-primary |
| `SQLITE_EXPORT_HISTORICAL_CSV` | `0` (D8B) | Export `historical_jobs.csv` from `historical_jobs_view` after dual-write |
| `SQLITE_EXPORT_DESCRIPTIONS_CSV` | `0` (D8B) | Export `job_descriptions.csv` from DB after dual-write |
| `SQLITE_EXPORT_CRM_CSV` | `0` (D8B) | Export `recruiter_crm.csv` from recruiters table after dual-write |
| `SQLITE_DASHBOARD_WRITE` | `1` (D8B) | Streamlit persists job editor + CRM edits to SQLite |
| `SQLITE_FAIL_ON_ERROR` | `0` | `1` = raise on DB write failure; `0` = log and continue |

Dual-write runs only when **both** `SQLITE_ENABLED=1` and `SQLITE_DUAL_WRITE=1`. Terminal summary shows `enabled=1` / `success=1` when writes commit.

### SQLite command reference

| Script | Command | When to use | Safety |
|--------|---------|-------------|--------|
| DB init | `python scripts/db_init.py` | First machine setup; after pulling schema migrations; before import | Safe |
| DB status | `python scripts/db_init.py --status-only` | Check DB file + Alembic revision without migrating | Safe |
| CSV import | `python scripts/import_csv_memory.py --dry-run` | Preview Phase B import row actions | Safe |
| CSV import (commit) | `python scripts/import_csv_memory.py` | Bootstrap or **re-sync** SQLite from CSV after CSV-only runs or drift | Safe (DB only; CSV unchanged) |
| Import parity | `python scripts/validate_sqlite_parity.py --mode import` | After `import_csv_memory.py`; strict aggregate + per-key checks | Safe |
| Post-import parity | `python scripts/validate_sqlite_parity.py --mode post-dual-write` | Lighter key-level check (optional) | Safe |
| Production parity (daily) | `python scripts/validate_sqlite_parity.py --mode production` | After each acquisition run (SQLite-first; default mode) | Safe |
| Production parity (CI) | `python scripts/validate_sqlite_parity.py --mode production --fail-on-error` | Exit code 1 on strict DB/cohort failures only | Safe |
| CSV mirror sync (legacy) | `python scripts/validate_sqlite_parity.py --mode csv-mirror-sync` | Migration/recovery when CSV mirrors must match DB | Safe |
| Dual-write parity (deprecated) | `python scripts/validate_dual_write_parity.py` | Delegates to `csv-mirror-sync`; use production mode for daily ops | Safe |
| Identity inventory | `python scripts/identity_inventory.py` | Before import/parity; V2 fill rates + description rows not in historical | Safe |
| SQLite orphan cleanup | `python scripts/cleanup_sqlite_orphan_job.py --dry-run` | Preview removal of one `JOB_KEY_V2` absent from CSV memory | Safe |
| SQLite orphan cleanup (commit) | `python scripts/cleanup_sqlite_orphan_job.py --job-key-v2 'v2:...'` | Remove a confirmed SQLite-only job orphan | **Destructive** (DB only) |
| D0 shadow read parity | `python scripts/shadow_read_parity.py` | Compare CSV vs SQLite read views (no production read switch) | Safe |
| D0 shadow (strict exit) | `python scripts/shadow_read_parity.py --fail-on-error` | Exit 1 on key/field shadow failures | Safe |
| D1 dashboard loader tests | `pytest tests/test_dashboard_loaders.py -q` | Unit tests for `SQLITE_READ` routing and fallbacks | Safe |
| D2 export gate tests | `python -m unittest tests.test_d2_export tests.test_db_read_views tests.test_dual_write_metadata -q` | D2 export + view metadata + dual-write linkage | Safe |
| D4 pipeline read tests | `python -m unittest tests.test_pipeline_read tests.test_db_read_views -q` | Historical index + description store DB reads; routing fixture | Safe |
| D5 write-primary tests | `python -m unittest tests.test_write_primary tests.test_dual_write_metadata tests.test_d2_export -q` | CSV write gating + DB export helpers | Safe |
| D6 dashboard tests | `python -m unittest tests.test_dashboard_loaders -q` | CRM loader + dashboard DB write round-trip | Safe |
| D7 reset/export tests | `python -m unittest tests.test_reset_sqlite -q` | SQLite truncate profiles + SOT parity detection | Safe |
| CSV memory export | `SQLITE_ENABLED=1 python scripts/export_csv_memory.py --all` | Export all CSV/JSON mirrors from DB | Safe |
| SOT parity validator | `python scripts/validate_sqlite_parity.py --mode source-of-truth --fail-on-error` | DB reference vs on-disk CSV exports | Safe |
| Metadata backfill (dry-run) | `python scripts/backfill_observation_query_runs.py --dry-run` | Preview `query_run_id` repair for latest run | Safe |

**Note:** Importer is **non-destructive** — it upserts CSV keys but does not delete DB rows for keys removed from CSV. Orphans can cause import-mode aggregate failures until cleaned (see workflows below).

### PASS / WARN / FAIL interpretation

| Validator | Section | PASS | WARN | FAIL |
|-----------|---------|------|------|------|
| `validate_sqlite_parity --mode import` | LIFECYCLE INVARIANTS | No failures listed | *(none)* | Any listed failure |
| | IMPORT PARITY (strict) | No failures listed | *(none)* | e.g. `ai_status aggregate mismatch`, row-count floors |
| | OVERALL | Both sections PASS | — | Any import failure |
| `validate_sqlite_parity --mode post-dual-write` | LIFECYCLE / OPERATIONAL | No strict failures | — | Strict failures listed |
| | CUMULATIVE MEMORY HEALTH | No warnings | Extra DB keys vs historical; DB scored > CSV | Historical keys missing in DB |
| `validate_sqlite_parity --mode production` | DB HEALTH + OPERATIONAL | No strict failures | Query state JSON drift; D2 metadata gaps | Missing DB eval, orphan links, cohort mismatch |
| | CUMULATIVE HEALTH (DB-first) | No strict failures | Jobs without eval; description gap | Historical keys in CSV missing from DB |
| | OVERALL | No strict failures | Warnings OK | Strict failures |
| `validate_sqlite_parity --mode csv-mirror-sync` | LIFECYCLE + OPERATIONAL PARITY | No strict failures | Cumulative CSV superset warnings | Strict failures (e.g. jobs not in historical, recruiter CSV count) |
| | OVERALL | No strict failures | Warnings OK | Strict failures |

`--fail-on-error` sets exit code **1** only when **strict failures** exist; **warnings do not fail** the process.

### Recommended execution order

**A. First-time SQLite setup**

```bash
python scripts/db_init.py
python scripts/import_csv_memory.py --dry-run
python scripts/import_csv_memory.py
python scripts/validate_sqlite_parity.py --mode import
python scripts/validate_sqlite_parity.py --mode production --fail-on-error
```

**B. Normal acquisition (D8B default)**

```bash
export OPENAI_API_KEY="..."
python main.py
python scripts/validate_sqlite_parity.py --mode production --fail-on-error
```

**C. After CSV-only runs** (`SQLITE_ENABLED=0` — CSV updated, DB stale)

```bash
python scripts/identity_inventory.py
python scripts/import_csv_memory.py
python scripts/validate_sqlite_parity.py --mode import
python scripts/validate_sqlite_parity.py --mode production --fail-on-error
```

### Import parity workflow

Use when bringing SQLite back in sync with CSV or validating Phase B bootstrap.

1. `python scripts/identity_inventory.py` — note `description rows with V2 not in historical` (CSV description orphans).
2. `python scripts/db_init.py` — ensure schema at head.
3. `python scripts/import_csv_memory.py` — upsert jobs, evaluations, descriptions, recruiters from CSV.
4. `python scripts/validate_sqlite_parity.py --mode import` — expect **OVERALL: PASS**.
5. If FAIL on aggregates (+1 DB row): run `python scripts/cleanup_sqlite_orphan_job.py` for the reported key (only if absent from `historical_jobs.csv` and `jobs.csv`), then re-validate.
6. If FAIL on `job_descriptions` count: remove description CSV rows whose `JOB_KEY_V2` is not in `historical_jobs.csv`, then re-validate (import does not delete stale description rows in DB until job row is gone).

### Production validation workflow (daily)

Use after each acquisition run under D8B write-primary.

1. Confirm last run logged `SQLITE DUAL-WRITE SUMMARY` with `enabled=1` and `success=1`.
2. `python scripts/validate_sqlite_parity.py --mode production` — review DB health, operational cohort, warnings.
3. `python scripts/validate_sqlite_parity.py --mode production --fail-on-error` — daily automation gate.

### CSV mirror sync workflow (legacy / migration)

Use when CSV mirrors are expected fully populated (after export or legacy dual-write).

1. `python scripts/export_csv_memory.py --all` (if validating post write-primary acquisition).
2. `python scripts/validate_sqlite_parity.py --mode csv-mirror-sync --fail-on-error`.
3. Deprecated alias: `python scripts/validate_sqlite_parity.py --mode production --fail-on-error` (same as step 2).

### SQLite recovery workflow

| Symptom | Action |
|---------|--------|
| DB errors mid-run | `SQLITE_DUAL_WRITE=0` or `SQLITE_ENABLED=0`; re-run `python main.py` (CSV must succeed) |
| Wrong routing splits / cache misses (D4) | `SQLITE_PIPELINE_READ=0` (instant CSV read fallback); optional `SQLITE_QUERY_STATE_READ=0` |
| CSV persistence issues (D5) | `SQLITE_WRITE_PRIMARY=0`; re-enable individual `SQLITE_EXPORT_*_CSV=1` if dashboard needs CSV |
| Dashboard edit drift (D6) | `SQLITE_DASHBOARD_WRITE=0` or re-export via `scripts/export_csv_memory.py --all` |
| CSV/DB drift after CSV-only period | `python scripts/import_csv_memory.py` then validate (§ import parity workflow) |
| Single SQLite job orphan (not in CSV) | `python scripts/cleanup_sqlite_orphan_job.py --dry-run` then commit |
| Description CSV orphan (in `job_descriptions.csv`, not in historical) | Remove row from CSV or restore job to historical; then import/validate |
| Severe DB corruption | Archive → optional delete `data/ai_job_agent.db` → `db_init` → `import_csv_memory.py` |
| Abandon SQLite (emergency) | `SQLITE_ENABLED=0` on `main.py` and Streamlit; CSV-only path |
| SOT validator FAIL after acquisition | Run `python scripts/export_csv_memory.py --all` first (write-primary skips mid-run CSV writes) |
| Production validator FAIL on empty historical/CRM | Wrong mode — use `--mode production`, not `csv-mirror-sync` or deprecated dual-write script |
| Dual-write `enabled=0` with defaults on | Check run logs for DB errors; verify `sqlite_flag()` / `SQLITE_ENABLED` not forced to `0` in env |

**Safety net:** `./scripts/archive_state.sh` before destructive CSV or DB operations.

---

## 11. Git workflow (common for this repo)

| Command | What it does | When to use | Safety |
|---------|--------------|-------------|--------|
| `git status` | Shows changed files | Before commit | Safe |
| `git diff` | Shows code changes | Review before commit | Safe |
| `git add <files>` | Stages changes | Preparing commit | Safe |
| `git commit -m "message"` | Saves snapshot locally | After review | Safe |
| `git push origin main` | Publishes to GitHub | Share updates | Safe (verify no secrets) |

### Before pushing (portfolio / public safety)

See `docs/PUBLIC_REPO.md`. Quick checks:

- `data/` must stay gitignored (only `data/.gitkeep` tracked)
- Do not commit `data/*.csv`, auth JSON, or `archive/reset-*` with real hiring data
- Grep for API keys and personal emails in staged files

| Command | What it does | Safety |
|---------|--------------|--------|
| `git check-ignore -v data/jobs.csv` | Confirms gitignore works | Safe |
| `git ls-files '*.csv'` | Lists tracked CSVs (should be templates/archives only) | Safe |

---

## 12. Operational workflows (cheat sheet)

### A. First-time developer setup

```bash
cd ai-job-agent
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
playwright install chromium
export OPENAI_API_KEY="..."
```

Then create auth files via scraper login flows → run `python main.py` → `streamlit run dashboard/app.py`.

### B. Daily refresh

```bash
source venv/bin/activate
export OPENAI_API_KEY="..."
python main.py
python scripts/validate_sqlite_parity.py --mode production --fail-on-error
streamlit run dashboard/app.py
```

Profile edits: [`config/profiles/ai_candidate_profile.example.md`](../config/profiles/ai_candidate_profile.example.md) (or `AI_CANDIDATE_PROFILE_PATH`) before run. Full cadence: [PRODUCTION_OPERATIONS.md](./PRODUCTION_OPERATIONS.md) §3.

### C. Cheap validation run (minimal scrape)

```bash
LINKEDIN_MAX_RUNS=0 INSTAHYRE_MAX_RUNS=1 \
GREENHOUSE_MAX_RUNS=0 LEVER_MAX_RUNS=0 WEWORKREMOTELY_MAX_RUNS=0 \
python main.py
```

### D. Debug a failing source

```bash
# Example: LinkedIn only, verbose
LINKEDIN_MAX_RUNS=1 INSTAHYRE_MAX_RUNS=0 GREENHOUSE_MAX_RUNS=0 LEVER_MAX_RUNS=0 WEWORKREMOTELY_MAX_RUNS=0 \
DEBUG_LINKEDIN=true python main.py
```

### E. Clean reset cycle (bootstrap)

```bash
./scripts/archive_state.sh
# Note RESET_ID from output
./scripts/reset_state.sh --archive-id reset-YYYYMMDD-HHMM --profile bootstrap
python main.py
python3 scripts/validate_bootstrap.py
```

Bootstrap truncates SQLite product tables when `SQLITE_ENABLED` is on (default via `sqlite_flag()` — no env export). Optional rehydrate from archive CSVs + `import_csv_memory.py` — see [PRODUCTION_OPERATIONS.md](./PRODUCTION_OPERATIONS.md) §2.

### F. SQLite bootstrap and parity (see §10b)

```bash
python scripts/db_init.py
python scripts/import_csv_memory.py
python scripts/validate_sqlite_parity.py --mode import
python main.py
python scripts/validate_sqlite_parity.py --mode production --fail-on-error
```

---

## 13. Key output files (after a successful run)

| Tier | Path | Role |
|------|------|------|
| **Authoritative (SQLite)** | `data/ai_job_agent.db` | Default source of truth (jobs, evaluations, descriptions, recruiters, runs) |
| **Authoritative (views)** | `current_jobs_view`, `historical_jobs_view`, `active_recruiters_view` | Dashboard and D2 export read these |
| **Export / legacy CSV** | `data/jobs.csv` | Generated from `current_jobs_view` when `SQLITE_EXPORT_JOBS_CSV=1` (default) |
| **Export / legacy CSV** | `data/historical_jobs.csv`, `data/job_descriptions.csv`, `data/recruiter_crm.csv` | Off by default under write-primary; refresh via `export_csv_memory.py --all` |
| **Deprecated** | `data/job_state.csv` | Legacy; merged into `user_job_state` on import |
| **Auth (file-only)** | `data/linkedin_auth.json`, `data/instahyre_auth.json` | Never in DB |
| **Orchestration** | `data/.linkedin_query_state.json` | LinkedIn cooldown mirror (JSON write-through) |
| **Logs** | `logs/` | Debug screenshots (e.g. Instahyre) |

---

## 14. Troubleshooting quick reference

| Symptom | Likely fix |
|---------|------------|
| `No module named 'paths'` | `pip install -e .` or `pip install -r requirements.txt` |
| `No module named 'agent'` | Same as above |
| Playwright browser missing | `playwright install chromium` |
| Empty dashboard | Run `python main.py` first; confirm `data/ai_job_agent.db` exists; check `SQLITE_READ` not forced to `0` |
| LinkedIn always skipped | Check `LINKEDIN_MAX_RUNS=0` not set; check `data/linkedin_auth.json` |
| Instahyre zero cards | Run `scripts/instahyre_dom_probe.py`; check `data/instahyre_auth.json` |
| AI batches fail | Verify `OPENAI_API_KEY`; try `DEBUG_AI=true`; confirm profile file loads (terminal char count) |
| Memory looks wiped | Check archive restore; bootstrap reset clears DB + CSV headers |
| `SQLITE DUAL-WRITE` `enabled=0` | Unset `SQLITE_ENABLED=0` / `SQLITE_DUAL_WRITE=0` in env; inspect DB errors in run log |
| SOT validator FAIL after run | Run `export_csv_memory.py --all` then re-validate (write-primary skips CSV mirrors) |
| CSV/DB parity FAIL | See §10b import parity workflow; run `import_csv_memory.py` after CSV-only runs |
| Import parity +1 scored | SQLite orphan not in historical — `cleanup_sqlite_orphan_job.py` or re-import after CSV fix |
| `job_descriptions` count mismatch | Description row in CSV without historical parent — prune CSV row (§10b) |
| Dashboard shows stale CSV | `SQLITE_READ=0` or `SQLITE_ENABLED=0` set — remove overrides or export from DB |

---

*Generated from repository source as of the `src/agent` + `data/` layout. For portfolio publishing, see `docs/PUBLIC_REPO.md`. SQLite operations: **§10b** (canonical).*
