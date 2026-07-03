# Autonomous Career Intelligence Platform

An AI-powered job intelligence system that aggregates opportunities across multiple hiring channels, normalizes and deduplicates them, scores fit against a candidate profile, and surfaces actionable recommendations through operational dashboards and recruiter-aware memory.

Built for product-minded operators who want **signal over noise** — with transparent pipeline stages, explainable scoring, and production-grade observability.

![Python](https://img.shields.io/badge/Python-3.12%2B-blue)
![Streamlit](https://img.shields.io/badge/Dashboard-Streamlit-FF4B4B)
![SQLite](https://img.shields.io/badge/Memory-SQLite-003B57)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

**[Product Walkthrough](#product-walkthrough)** · **[Quick Start](#quick-start)** · **[Documentation](#documentation)** · **[Clone setup](docs/CLONE_SETUP.md)**

---

## Why I Built This

Job searching today is not really a search problem — it is an **operations problem**.

The same role shows up on LinkedIn, on an ATS board, and on a niche marketplace. Titles look similar but responsibilities differ. A listing from last week may still be open, or it may already be stale. And every time you open a new tab, you lose context: who posted the role, whether you already saw it, and whether it is actually a fit for your level and domain.

I started with scraper scripts because I needed more reach than manual browsing. That helped me collect jobs, but it did not help me **decide**. I still had duplicates, noisy titles, no memory between runs, and no consistent way to explain why one role was worth my time and another was not.

So I rebuilt the approach as a **career intelligence platform**:

- **Orchestration** — Multiple sources run in a governed pipeline, not as one-off scripts.
- **Memory** — Historical state, stored descriptions, and recruiter metadata persist across runs so the system learns what it has already processed.
- **Layered filtering** — Fast relevance checks first, then deeper AI scoring only where it adds value.
- **Explainability** — Scores come with reasons tied to domain, responsibilities, and seniority — not just keyword matches.

The goal is not to automate "apply to everything." It is to create a **repeatable intelligence layer** that turns fragmented listings into a short, explainable list of opportunities worth human attention. Listing freshness and availability are tracked over time so the dashboard reflects what is still open — not just what was scraped last week.

---

## Problem

Modern job search is not limited to one website. The same company may post on LinkedIn, an ATS board, and a niche marketplace. Titles compress real scope into a few words. Freshness, level, and domain fit are hard to judge from a card view alone. For a focused search, volume is manageable in theory; in practice it becomes an operations problem: too many tabs, too little memory, and too much repeated mental work.

Common approaches break down in predictable ways:

- **Manual tracking** (spreadsheets, Notion, starred tabs) works until source count grows — you re-enter jobs, reconcile duplicates by hand, and lose recruiter context between sessions.
- **Single-source alerts** reduce noise in one channel but miss the rest of the market and rarely store full descriptions or scoring logic across runs.
- **One-off scrapers** increase reach but do not create a governed workflow: no stable identity across URLs, no incremental routing, no explainable ranking.
- **Title-only filters** are fast but brittle — adjacent roles often look identical in the title while differing sharply in responsibilities and seniority.

---

## Solution

This repository implements a **governed career intelligence pipeline**, not a dump of scraped rows.

- **Fragmented ecosystem → unified ingestion.** Multiple hiring channels feed one normalization and identity layer, with per-source run caps so acquisition stays deliberate.
- **Noise and duplicates → layered filtering.** Stage-1 relevance removes obvious mismatches cheaply; deduplication runs before expensive description fetch and AI calls.
- **No run-to-run memory → incremental routing.** Historical state splits each job into brand new, needs-AI-only, or fully processed paths.
- **Shallow matching → AI scoring on full text.** Batched evaluation against a defined candidate profile produces a score and a short reason — not a keyword hit.
- **Listings without relationships → recruiter-aware memory.** Hiring contact metadata syncs into a CRM-style store so opportunities are part of an ongoing market map.
- **Stale listings without visibility → lifecycle monitoring.** A scheduled monitor updates listing availability so recommendations and tables reflect what is still open.
- **Opaque batch jobs → operational visibility.** Run summaries, health KPIs, and scheduler controls are built for someone monitoring a live pipeline.

Under the hood: SQLite product memory, a Streamlit operator dashboard, and macOS launchd scheduling for unattended runs. See the [Product Walkthrough](#product-walkthrough) for the surface experience and [System architecture](#system-architecture) for the platform map.

---

## Outcome

For a recruiter or hiring manager reviewing this work, the useful signal is not scrape volume. It is whether the system produces a **smaller, explainable shortlist** with enough context to judge fit quickly: who is behind the role, why it ranked, and what changed since the last run.

- **Less repeated work** — Incremental routing spends effort on net-new jobs instead of replaying the full pipeline every run.
- **Lower AI cost** — Cheaper gates run before batch scoring; stored descriptions are reused when already captured.
- **Faster PM relevance** — Semantic scoring reads full descriptions when titles alone are misleading.
- **Cleaner intelligence** — Layered deduplication reduces the same listing appearing under multiple URLs.
- **Persistent relationships** — Recruiter and hiring-manager context survives across acquisition runs.
- **Inspectable operations** — Health sections and scheduler controls make production behavior visible, not buried in logs.
- **Listing truth over time** — Lifecycle monitoring keeps `listing_status` current so queues and tables do not surface closed roles as actionable.

### Sample ranked recommendations

Recommendations are produced after layered filtering and AI scoring against a defined candidate profile. Examples below are anonymized outputs representative of historical pipeline runs.

<span style="color:#0969da">**Company names and identifiers have been anonymized for portfolio presentation.**</span>

| Company | Role | AI Score | AI Recommendation |
|---------|------|----------|-------------------|
| B2C AI subscription (Remote) | Product Manager | 9 | **Recommend.** Strong alignment with ownership-heavy B2C product work, AI-led growth, and experimentation. |
| Payments infrastructure (India) | Product Manager II | 7 | **Moderate fit.** Solid fintech scope and execution ownership. Review level and location before raising priority. |
| India payments platform | Product Growth Manager | 5 | **Conditional.** Relevant growth domain, but the JD is analytics- and SQL-heavy versus strategy-led PM work. Quick scan only. |
| Large cloud platform | Product Manager, GPU-as-a-Service | 2 | **Low relevance.** Infrastructure-focused GPU platform role with a senior technical bar. Outside target PM scope and seniority band. |

Scoring rules and profile configuration: [config/profiles/README.md](config/profiles/README.md) and [PROJECT_COMMAND_REFERENCE.md §8](docs/PROJECT_COMMAND_REFERENCE.md#8-streamlit-dashboard).

---

## Quick Start

You do not need to run code to understand what this project does. Think of it as three layers:

| Layer | What it does | What you see |
|-------|----------------|--------------|
| **Collect** | Gathers roles from hiring channels you configure | New jobs enter the system each run |
| **Organize** | Removes duplicates and applies relevance rules | A cleaner, de-duplicated set of roles |
| **Recommend** | AI scores fit against a defined candidate profile | Ranked opportunities with short explanations |

**In plain language:** jobs come in from LinkedIn, Instahyre, and optional ATS boards → the pipeline cleans and filters them → AI adds a second opinion on fit where the title alone is misleading.

**If you are reviewing this as a hiring manager or recruiter:**

- *Does this person think in systems?* — The walkthrough below shows intentional product design across acquisition, decision queues, relationships, and operations.
- *Is the output actionable?* — Scored jobs include a **reason**, not just a number.
- *Can they operate it in production?* — Scheduler health, pause/resume controls, and parity validation are first-class UI concerns.

**To see the product surface:** scroll to the [Product Walkthrough](#product-walkthrough), or run `./scripts/run_dashboard.sh` after a local install.

**For engineers:** `python main.py` then `./scripts/run_dashboard.sh` — full steps in [docs/CLONE_SETUP.md](docs/CLONE_SETUP.md).

This repository does not ship API keys, login sessions, or live job data (private/local by design).

---

## Product Overview

This platform turns fragmented job listings into a **single career intelligence layer**:

| Problem | How the platform addresses it |
|--------|-------------------------------|
| Jobs scattered across channels | Multi-source acquisition with per-source orchestration and run caps |
| Duplicate listings and unstable URLs | Dual identity system (legacy + V2) with layered deduplication |
| Shallow title-only filtering | Stage-1 rules plus semantic AI scoring on full descriptions |
| Lost context between runs | SQLite product memory, incremental routing, description store |
| Stale or closed listings | Lifecycle monitor updates `listing_status` on each job |
| No visibility into production runs | Acquisition Health, Monitor Health, AI Refresh Health, Operational Controls |
| Re-scoring without re-scraping | Refresh AI Evaluations (dashboard or CLI) |
| Relationships and outreach scattered | Recruiter CRM + Outreach Intelligence below the job table |

The system is designed as a **personal career copilot** that can be demonstrated to recruiters, hiring managers, and product/AI teams as a serious orchestration product — not a one-off scraper script.

Capability maturity and limitations: [docs/PRODUCT_STATUS_SUMMARY.md](docs/PRODUCT_STATUS_SUMMARY.md).

---

## Key Features

### Acquisition

- LinkedIn query orchestration, Instahyre feeds, Greenhouse, Lever, WeWorkRemotely
- Instahyre Interested sync — list-only harvest that marks Applied state without re-running the full AI pipeline
- Per-source `*_MAX_RUNS` gates to keep runs deliberate and cost-bounded

### Intelligence

- Stage-1 relevance filter before expensive steps
- V2 identity, exact URL, and fuzzy title/company deduplication
- Incremental routing: brand-new vs needs-AI-only vs fully processed vs user-managed CRM stages
- AI batch scoring with structured `ai_score` + `reason` per job
- Manual **Refresh AI Evaluations** to re-score existing jobs without re-scraping

### Listing lifecycle

- Scheduled lifecycle monitor (Scheduler B) checks listing availability
- `listing_status` drives Recommended Actions and dashboard visibility (`open` / `closed` / `removed`)
- LinkedIn applied detection can auto-promote discovery-stage jobs and set `monitor_exempt`

### Dashboard

- Job Search Progression (Discovery → Application → Outcomes) and source distribution
- Four-queue **Recommended Actions** Command Center on scored discovery jobs
- Sidebar-filtered **Job Listings** with Listing/Age columns and hiring-manager edit
- **Recruiter Relationship Manager** with stage progression
- **Outreach Intelligence** — opportunity-centric attempt log (V1–V1.3)

### Operations

- macOS launchd: acquisition **09:00 / 21:00 IST**, lifecycle monitor **17:00 IST** daily
- Operational Controls: pause/resume schedulers, run-now triggers, AI refresh dialog
- Post-run SQLite parity validation

Command and flag detail: [PROJECT_COMMAND_REFERENCE.md](docs/PROJECT_COMMAND_REFERENCE.md).

---

## Product Walkthrough

The Streamlit dashboard is where acquisition output becomes decisions. The tour below follows how an operator — or a reviewer evaluating the product — would experience the platform: from headline health, through what to act on, through relationships and outreach, then how data flows in, and finally how production runs are controlled.

### Dashboard overview

Opening the dashboard, you see whether the system is current: last acquisition and monitoring refresh, total jobs in memory, recruiter count, and how discovery jobs are distributed across pipeline stages and sources. This is the orientation layer — before diving into queues, you know if today's run landed and how large the working set is.

<p align="center">
  <img src="./diagrams/dashboard-hero.png" alt="Streamlit dashboard header: KPIs, Job Search Progression stage cards, and Source Distribution" width="720" />
</p>

### Recommended Actions Command Center

Once jobs are scored, the question is not "what exists?" but "what deserves attention today?" Four waterfall queues — **High Confidence**, **Apply Today**, **Apply This Week**, and **Needs Review** — surface discovery-stage jobs by score and age. Each card links to the posting, shows the AI score, and offers **Applied ✓** on the apply-oriented queues so progress is recorded without leaving the dashboard. **Why?** opens the full rationale behind the score.

<p align="center">
  <img src="./diagrams/dashboard-recommended-actions.png" alt="Recommended Actions Command Center: four-queue 2×2 grid with High Confidence, Apply Today, Apply This Week, and Needs Review" width="720" />
</p>

Only `listing_status=open` jobs appear in these queues — closed listings drop out automatically after the lifecycle monitor runs.

### Job Listings

When you need the full table — not just the shortlist — Job Listings provides a sidebar-filtered view of the visibility cohort. **Listing** and **Age** columns show availability and freshness; open and closed jobs remain visible for context while removed listings stay hidden. Hiring Manager can be edited inline, which flows into recruiter CRM when dashboard writes are enabled.

<p align="center">
  <img src="./diagrams/dashboard-job-listings-listing-status.png" alt="Job Listings table with Listing and Age columns under listing_status visibility" width="720" />
</p>

### Recruiter CRM

Jobs are not isolated URLs — they connect to people. The Recruiter Relationship Manager tracks hiring contacts discovered during acquisition: stage progression from discovered through warm, active, and responded, plus an editable CRM table. Metrics reflect relationship workflow stages, not just whether a name appeared once in a scrape.

<p align="center">
  <img src="./diagrams/dashboard-crm.png" alt="Recruiter Relationship Manager: stage progression cards and CRM table" width="720" />
</p>

### Outreach Intelligence

Below CRM, **Outreach Intelligence** logs outreach *attempts* tied to opportunities — separate from recruiter stage management. KPIs cover active outreach, follow-ups due, and overdue items. New records can be prefilled from job listings or LinkedIn posts (V1.2–V1.3), so the log captures what was said, when, and in what context without replacing the CRM.

*Screenshot: capture pending — see [PROJECT_COMMAND_REFERENCE.md §8](docs/PROJECT_COMMAND_REFERENCE.md#outreach-intelligence-v1) for layout detail.*

### End-to-end pipeline

Everything above is fed by a governed batch pipeline. New jobs pass Stage-1 filtering and deduplication before descriptions are fetched and AI scoring runs; repeat jobs route through incremental paths so prior work is not replayed. Instahyre adds a two-phase path: feed acquisition, then Interested sync for Applied-state updates.

<p align="center">
  <img src="./diagrams/pipeline_flow.png" alt="End-to-end pipeline flow from multi-source acquisition through filtering and AI scoring to the dashboard" width="520" />
</p>

Typical routing: **brand new** → Stage 1 → dedup → descriptions → AI · **needs AI only** → AI queue directly · **fully processed** → merge from memory · **user-managed CRM stages** → skip AI (`not_required`).

### System architecture

At platform scale, ingestion, SQLite product memory, filtering, AI scoring, lifecycle monitoring, and the Streamlit layer form one path from fragmented listings to actionable recommendations. Multi-source acquisition runs under per-source caps; macOS launchd triggers scheduled acquisition and monitor runs in production.

![System architecture](./diagrams/architecture-diagram.png)

Diagram inventory: [docs/REPOSITORY_MAP.md §2.1](docs/REPOSITORY_MAP.md#21-diagram-assets). Data model depth: [docs/SQLITE_PRODUCT_MEMORY_ARCHITECTURE.md](docs/SQLITE_PRODUCT_MEMORY_ARCHITECTURE.md).

### Operator Controls

Production operation needs more than a cron line in a README. **Operational Controls** exposes acquisition and lifecycle schedulers in the dashboard: pause, resume, and run-now when writes are enabled. **Refresh AI Evaluations** triggers a manual re-score run with a preset picker — useful when the candidate profile changes but you do not want to re-scrape every listing.

<p align="center">
  <img src="./diagrams/dashboard-operator-controls.png" alt="Operational Controls: Acquisition, Lifecycle Monitor, and Refresh AI Evaluations cards" width="720" />
</p>

Technical detail: [PROJECT_COMMAND_REFERENCE.md §8 — Operational Controls](docs/PROJECT_COMMAND_REFERENCE.md#operational-controls).

### Acquisition Health

Each acquisition run writes structured outcomes to SQLite. **Acquisition Health** summarizes the latest Scheduler A run — observations ingested, query runs, duration — and surfaces run history so you can confirm twice-daily runs succeeded without opening log files.

<p align="center">
  <img src="./diagrams/dashboard-acquisition-health.png" alt="Acquisition Health: summary KPIs and acquisition run history table" width="720" />
</p>

### Lifecycle Monitor Health

Listing availability changes after the initial scrape. **Operational Monitor Health** (Scheduler B) reports the latest lifecycle monitor run: jobs checked, status transitions, and duration. This is what keeps Recommended Actions honest about which roles are still open.

<p align="center">
  <img src="./diagrams/dashboard-monitor-health.png" alt="Operational Monitor Health: summary KPIs and lifecycle monitor run history" width="720" />
</p>

### AI Refresh Health

When you re-score without re-scraping, **AI Refresh Health** shows the latest completed manual refresh: preset used, jobs scored, cohort size, eligible count, duration, and batch failures. Run history makes it easy to compare one refresh against the next after a profile update.

<p align="center">
  <img src="./diagrams/dashboard-ai-refresh-health.png" alt="AI Refresh Health: two-row KPIs and AI refresh run history" width="720" />
</p>

### AI Refresh preview dialog

Before committing API spend, the refresh dialog shows an operator-friendly preview: current cohort size, jobs ready for scoring, and an estimated request count — without internal batch terminology. The preview updates when you change preset (`backlog` vs `discovery`).

<p align="center">
  <img src="./diagrams/dashboard-ai-refresh-popup.png" alt="Run Refresh AI Evaluations dialog with preset picker and operator-friendly preview card" width="720" />
</p>

---

## Documentation

Implementation depth lives here — the README is the product tour.

| Doc | Purpose |
|-----|---------|
| [docs/CLONE_SETUP.md](docs/CLONE_SETUP.md) | **First-time install** — clone, venv, `db_init`, first run |
| [docs/PRODUCT_STATUS_SUMMARY.md](docs/PRODUCT_STATUS_SUMMARY.md) | **Status snapshot** — capability maturity, limitations, milestones |
| [docs/REPOSITORY_MAP.md](docs/REPOSITORY_MAP.md) | **Codebase navigation** — structure, data flow, subsystem map |
| [docs/SCHEDULER_SETUP.md](docs/SCHEDULER_SETUP.md) | **Scheduling** — macOS launchd install, 09:00 / 21:00 acquisition, 17:00 monitor |
| [docs/PRODUCTION_OPERATIONS.md](docs/PRODUCTION_OPERATIONS.md) | **Operator procedures** — daily workflow and reset checklist |
| [docs/PROJECT_COMMAND_REFERENCE.md](docs/PROJECT_COMMAND_REFERENCE.md) | **Commands and dashboard** — §8 layout, §10b flags and troubleshooting |
| [docs/SQLITE_IMPLEMENTATION_PLAN.md](docs/SQLITE_IMPLEMENTATION_PLAN.md) | Migration history and rollback reference |
| [docs/SQLITE_PRODUCT_MEMORY_ARCHITECTURE.md](docs/SQLITE_PRODUCT_MEMORY_ARCHITECTURE.md) | SQLite data model and product memory design |
| [docs/PUBLIC_REPO.md](docs/PUBLIC_REPO.md) | Maintainer note for this portfolio mirror |
| [config/profiles/README.md](config/profiles/README.md) | Example AI candidate profile |

---

## Disclaimer — Showcase vs Private Operation

This repository is intended as a **professional showcase** of product thinking, pipeline design, and operational maturity:

- **Credentials and live data are not included** — auth JSON, database contents, and logs stay local under `data/` (gitignored).
- **Candidate profile:** [`config/profiles/ai_candidate_profile.example.md`](config/profiles/ai_candidate_profile.example.md) (override with `AI_CANDIDATE_PROFILE_PATH` for a private profile).
- **Run caps** may be tuned for validation; adjust `*_MAX_RUNS` for production economics.
- **Scraping** depends on third-party site behavior; respect terms of service and rate limits.
- **AI scores are advisory** — not hiring decisions; always verify listings on source sites.

For interview or portfolio context: emphasize **orchestration**, **incremental memory**, **explainable AI**, and **operator-grade visibility** — not raw scrape volume.

---

## License

MIT License — see [LICENSE](LICENSE). Copyright (c) 2026 Vasundhara Bisht.
