# Product Status Summary

High-level snapshot for onboarding, roadmap reviews, and portfolio context. This document describes the **public clone**; live operator logs and promotion sign-off artifacts are not shipped in this repository.

**Last aligned with codebase:** D8B complete + flag remediation + externalized AI candidate profile (2026-06).

| Doc | Use when you need |
|-----|-------------------|
| [CLONE_SETUP.md](./CLONE_SETUP.md) | Fresh-machine install and first run |
| [PRODUCTION_OPERATIONS.md](./PRODUCTION_OPERATIONS.md) | How to run, reset, validate daily |
| [PROJECT_COMMAND_REFERENCE.md](./PROJECT_COMMAND_REFERENCE.md) §10b | Commands, flags, troubleshooting |
| [SQLITE_IMPLEMENTATION_PLAN.md](./SQLITE_IMPLEMENTATION_PLAN.md) | Migration history and rollback reference |
| [SQLITE_PRODUCT_MEMORY_ARCHITECTURE.md](./SQLITE_PRODUCT_MEMORY_ARCHITECTURE.md) | Data model and design depth |

---

## 1. Current product status

**Career Intelligence Platform** is a personal, single-operator job search product: multi-channel acquisition, layered filtering, AI-assisted prioritization with explainable scores, recruiter relationship management, and a Streamlit decision dashboard.

**Migration status:** D0–D8B complete. SQLite (`data/ai_job_agent.db`) is the **default operational source of truth**. After clone setup, run a bootstrap reset and validation pass ([PRODUCTION_OPERATIONS.md](./PRODUCTION_OPERATIONS.md) §2) before relying on daily cadence.

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

---

## 3. Current architecture summary

```text
Scrapers (LinkedIn, Instahyre, Greenhouse, Lever, WeWorkRemotely)
    → main.py pipeline (normalize → Stage-1 → dedup → descriptions → AI → merge)
    → SQLite dual-write (product memory)
    → Views (current_jobs_view, historical_jobs_view, active_recruiters_view, …)
    → Streamlit dashboard (read/write when flags on)
    → Optional CSV export (backup / handoff)
```

Visual: [diagrams/architecture-diagram.png](../diagrams/architecture-diagram.png)

Depth: [SQLITE_PRODUCT_MEMORY_ARCHITECTURE.md](./SQLITE_PRODUCT_MEMORY_ARCHITECTURE.md).

---

## 4. Current source of truth (SQLite)

| Concern | Authority |
|---------|-----------|
| Job memory, AI evaluations, descriptions | `data/ai_job_agent.db` |
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
- **UI:** `streamlit run dashboard/app.py` — sidebar should indicate SQLite data source under D8B defaults.
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
|----------|-----------|
| Acquisition | Scheduled or twice-daily `python main.py` (no flag exports) |
| Review | Streamlit dashboard for ranked jobs + CRM |
| Validation | `validate_sqlite_parity.py --mode production --fail-on-error` after runs |
| Backup | `archive_state.sh` + `export_csv_memory.py --all` + SOT validator |
| Profile tuning | Edit markdown profile before scoring runs |
| Emergency | `SQLITE_ENABLED=0` for CSV-only acquisition and dashboard |

Details: [PRODUCTION_OPERATIONS.md](./PRODUCTION_OPERATIONS.md).

---

## 9. Known limitations

- **Single-user, single profile** — no multi-tenant or per-persona DB profiles yet.
- **Scraper fragility** — third-party site changes can break acquisition paths.
- **AI cost cap** — `DEBUG_LIMIT` bounds scored jobs per run; remainder persisted as `skipped_by_cap`.
- **Description truncation** — `AI_DESCRIPTION_MAX_CHARS=3000` in scorer prep; very long postings may lose tail content (requirements/seniority at end).
- **SOT validator vs on-disk CSV** — `--mode source-of-truth` is for post-export backup checks; use `--mode production` after daily acquisition (not legacy dual-write parity).
- **Importer non-destructive** — DB orphans not removed by CSV import alone; cleanup scripts available.
- **No hosted API** — local Python + Streamlit only.
- **Manual Streamlit QA** — promotion relied on unit tests; periodic manual smoke recommended.
- **Public clone** — placeholder LinkedIn IDs in config; replace before live LinkedIn runs.

---

## 10. Immediate next roadmap items

1. Complete [CLONE_SETUP.md](./CLONE_SETUP.md) and **pre-production bootstrap reset** ([PRODUCTION_OPERATIONS.md](./PRODUCTION_OPERATIONS.md) §2).
2. Establish **daily cadence** (acquisition + dashboard + parity check).
3. Tune [`ai_candidate_profile.example.md`](../config/profiles/ai_candidate_profile.example.md) (or your private profile via `AI_CANDIDATE_PROFILE_PATH`) based on scoring quality.
4. Optional **manual Streamlit** smoke after reset.

---

## 11. Future roadmap themes

Canonical planning list (avoid duplicating in README):

| Theme | Direction |
|-------|-----------|
| **Ranking** | Separate metadata enrichment from sort signals (posted date, freshness) |
| **Salary** | Structured compensation parsing where sources expose it |
| **Pagination** | Deeper InstaHyre feed traversal |
| **API layer** | REST/GraphQL over pipeline outputs |
| **Alerting** | Slack/email digests for high-score matches |
| **Multi-user** | Isolated profiles and historical stores |
| **Testing** | Contract tests for identity, dedup, Stage-1 invariants |
| **Postgres** | Cloud evolution (out of current scope) |
| **CI** | Optional wiring for parity validators on schedule |

Profile variants per target role can use additional files under `config/profiles/` with `AI_CANDIDATE_PROFILE_PATH`.
