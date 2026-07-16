# Autonomous Career Intelligence

> An AI-powered career intelligence platform that turns fragmented job listings into explainable recommendations — with autonomous acquisition, durable product memory, and operator-grade dashboards.

<p align="center">
  <img src="./diagrams/dashboard-hero.png" alt="Autonomous Career Intelligence dashboard: KPIs, Recommended Actions, and source distribution" width="720" />
</p>

---

## About this repository

**This repository is a portfolio showcase.** The production acquisition engine, AI scoring, prioritization, and operational automation remain private. A live Demo Mode deployment is available here: **`<LIVE_DEMO_URL>`**.

This repo intentionally does not contain the acquisition, scoring, ranking, or outreach implementation — that's a deliberate IP decision, not an omission. What it does contain: an honest description of what was built, the architecture and AI system design behind it, real screenshots of the finished product, and a handful of standalone code excerpts that demonstrate engineering and UX craftsmanship in isolation. See [docs/ABOUT_THIS_REPO.md](docs/ABOUT_THIS_REPO.md) for the full reasoning.

## What it is

**Autonomous Career Intelligence** is an end-to-end job intelligence product. It ingests roles from multiple hiring channels, normalizes and deduplicates them, scores fit with AI against a candidate profile, and surfaces actionable next steps through a Streamlit dashboard — with recruiter relationship tracking, outreach intelligence, and operational health monitoring built in. It is built for candidates running a high-intent search who need a clear, repeatable answer to one question: which roles deserve attention now—and why.

## The problem

Modern job search is an **operations problem**, not a search problem. The same role appears on LinkedIn, an ATS board, and niche marketplaces. Titles hide seniority and domain. Context is lost between tabs and sessions. Spreadsheets and starred links do not scale when you care about **signal**, **explainability**, and **repeatability**. The result: high-fit roles get missed, low-fit roles consume attention, and follow-through becomes inconsistent across sessions.

## Why I built this

Most job tools were built for a simpler world: find a listing, save a link, track an application. Today's search generates too much volume, too much duplication, and too little continuity for that model to hold.

The product thesis is that job search needs a **single career intelligence layer**—not another spreadsheet. Alerts and trackers optimize discovery and record-keeping; this product optimizes **decision quality and execution cadence** across repeated runs.

It was built to compound context over time: turn fragmented listings into a smaller, explainable set of next actions a candidate can trust and act on—not a disposable list of links.

## Why not a traditional job tracker

This is not a Kanban board or application spreadsheet. It is a **governed intelligence pipeline**. Traditional trackers optimize record-keeping; this product optimizes decision quality and execution cadence.

| Traditional tracker | Autonomous Career Intelligence |
|---------------------|--------------------------------|
| Manual data entry | Multi-source autonomous acquisition |
| Title-only filters | Layered relevance + semantic AI scoring on full descriptions |
| No run-to-run memory | Continuity across runs so priorities don't reset |
| Opaque ranking | Scores with short, defensible reasons |
| Listings in isolation | Recruiter CRM, outreach intelligence, and health surfaces |

## Solution / Outcome

After using the product, job search stops feeling like tab-hopping and starts feeling like a managed workflow.

- **Unified view** — Roles from across channels appear in one place, deduplicated, instead of scattered across tabs.
- **Explainable prioritization** — A ranked shortlist with reasons—not opaque scores or keyword hits.
- **Sustained execution** — Context and relationships persist across sessions, with clear next-best actions for what to pursue now, review later, or skip.

## AI capabilities

- **Batch job scoring** — Semantic evaluation against an external candidate profile (domain, seniority, responsibilities); structured reasons, not keyword hits.
- **Recommended Actions** — Four-queue command center (High Confidence, Apply Today, Apply This Week, Needs Review); optional Priority Overlay for profile-driven reordering without changing stored scores.
- **AI-assisted outreach** — Draft outreach from hiring signals and job context.
- **Source & pipeline analytics** — Acquisition source intelligence and pipeline effectiveness views across providers.

Design rationale and guardrails: [docs/AI_SYSTEM_DESIGN.md](docs/AI_SYSTEM_DESIGN.md).

## Technology stack

| Layer | Technologies |
|-------|----------------|
| Language & orchestration | Python, batch pipeline |
| Product memory | SQLite, SQLAlchemy, Alembic migrations |
| Dashboard | Streamlit, Altair, pandas |
| Acquisition | Playwright (browser automation), REST APIs (ATS platforms) |
| AI | OpenAI Responses API |
| Matching | RapidFuzz deduplication, dual identity model |

## Why this is a strong portfolio project

**Product management:** Clear problem framing (signal over noise), a shipped operator surface (dashboard, queues, CRM, outreach, discovery), and explicit product boundaries (Demo Policy, sandbox vs Live, explainable AI).

**Engineering:** End-to-end system design — ingestion → normalization → memory → scoring → observability — with schedulers, health dashboards, migration discipline, and a public-safe Demo Mode.

**Differentiation:** Systems thinking beyond a demo scraper — incremental routing, recruiter-aware memory, listing lifecycle monitoring, company discovery catalog, and policy-gated automation.

---

## Live Demo

Explore the full dashboard, hosted, with no setup: **`<LIVE_DEMO_URL>`**

It's the real dashboard surface backed by an anonymized sandbox seed — Recommended Actions, listings, CRM, outreach, discovery, and health sections are all populated and interactive. External automation and live API calls are disabled in the sandbox. Full details: [docs/DEMO_MODE.md](docs/DEMO_MODE.md).

### Try a UI pattern locally

One small, standalone piece of the dashboard's UX is runnable directly from this repo, with no backend:

```bash
pip install -r requirements.txt
streamlit run showcase/ui_pattern_demo.py
```

See [showcase/README.md](showcase/README.md) for what else is in there.

---

## Documentation

| Doc | Purpose |
|-----|---------|
| [docs/ABOUT_THIS_REPO.md](docs/ABOUT_THIS_REPO.md) | Why this repo is curated the way it is |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | System design, pipeline flow, design principles |
| [docs/DATA_MODEL.md](docs/DATA_MODEL.md) | Product memory — what's tracked and why |
| [docs/AI_SYSTEM_DESIGN.md](docs/AI_SYSTEM_DESIGN.md) | AI scoring approach, guardrails, calibration philosophy |
| [docs/DEMO_MODE.md](docs/DEMO_MODE.md) | The hosted sandbox — what it is and how it's built |
| [config/profiles/README.md](config/profiles/README.md) | AI candidate profile format |

---

## Design deep dive

Job searching today fragments across channels with no unified memory layer. This product implements a **governed career intelligence pipeline**:

- **Fragmented ecosystem → unified ingestion** — Multiple hiring channels feed one normalization and identity layer.
- **Noise → layered filtering** — Cheap relevance checks before expensive description fetch and AI calls.
- **No memory → incremental routing** — Historical state splits jobs into brand-new, needs-AI-only, and fully-processed paths.
- **Shallow matching → AI scoring on full text** — Batched evaluation with score + reason per role.
- **Listings without relationships → recruiter-aware memory** — Hiring contact metadata persists in CRM-style storage.
- **Opaque batch jobs → operational visibility** — Run summaries, identity health, and dashboard health sections.

For recruiters and hiring managers reviewing this work: the signal is **smaller, explainable shortlists** with enough context to judge fit — who is behind the role, why it ranked, and what changed since the last run.

Full write-up: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

---

## End-to-End Pipeline Flow

<p align="center">
  <img src="./diagrams/pipeline_flow.png" alt="End-to-End Pipeline Flow: acquisition through dashboard" width="520" />
</p>

Details: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#pipeline-flow).

## System Architecture

![System Architecture](./diagrams/architecture-diagram.png)

Details: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Sample Ranked Recommendations

Recommendations are produced after layered relevance filtering and AI scoring against a defined candidate profile (domain, seniority, and responsibility fit). The examples below are anonymized outputs representative of historical pipeline runs.

<strong><span style="color:#0969da">Company names and identifiers have been anonymized for portfolio presentation.</span></strong>

| Company | Role | AI Score | AI Recommendation |
|---------|------|----------|-------------------|
| B2C AI subscription (Remote) | Product Manager | 9 | **Recommend.** Strong alignment with ownership-heavy B2C product work, AI-led growth, and experimentation. |
| Payments infrastructure (India) | Product Manager II | 7 | **Moderate fit.** Solid fintech scope and execution ownership. Review level and location before raising priority. |
| India payments platform | Product Growth Manager | 5 | **Conditional.** Relevant growth domain, but the JD is analytics- and SQL-heavy versus strategy-led PM work. Quick scan only. |
| Large cloud platform | Product Manager, GPU-as-a-Service | 2 | **Low relevance.** Infrastructure-focused GPU platform role with a senior technical bar. Outside target PM scope and seniority band. |

---

## Identity, deduplication, and recruiter intelligence

Every job is resolved to a stable identity across sources and re-runs, then deduplicated with an ordered strategy (exact source ID, exact application link, then guarded fuzzy matching) before any expensive work happens. Where a source exposes hiring-contact metadata, it's captured and tracked as a relationship over time — not just a listing attribute — feeding a recruiter CRM with relationship-stage tracking (discovered → warm → active → responded), plus a separate outreach-attempt log with follow-up tracking and AI-assisted drafting. Full design reasoning: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and [docs/DATA_MODEL.md](docs/DATA_MODEL.md).

<p align="center">
  <img src="./diagrams/dashboard-crm.png" alt="Recruiter Relationship Manager: relationship progression stage cards and CRM table" width="720" />
</p>

---

## Repository structure

```
autonomous-career-intelligence-platform/
├── README.md
├── LICENSE
├── SECURITY.md
├── requirements.txt
├── diagrams/                 # Architecture, pipeline, and dashboard visuals
├── docs/
│   ├── ABOUT_THIS_REPO.md    # Why this repo is curated the way it is
│   ├── ARCHITECTURE.md       # System design and pipeline flow
│   ├── DATA_MODEL.md         # Product memory, at a category level
│   ├── AI_SYSTEM_DESIGN.md   # AI scoring approach and guardrails
│   └── DEMO_MODE.md          # The hosted sandbox
├── config/
│   ├── ai_scoring_calibration_examples.md
│   └── profiles/              # Candidate profile format + public example
├── dashboard/
│   └── ui_help.py             # Real, standalone UX component (help-icon pattern)
├── src/db/
│   └── app_mode.py            # Real, standalone Live/Demo mode enum
├── showcase/                   # Standalone illustrative code excerpts
└── tests/
    └── test_showcase.py        # Tests for the showcase excerpts only
```

The acquisition adapters, AI scoring/ranking implementation, persistence layer, dashboard business logic, and operational tooling that power the Live product are private. See [docs/ABOUT_THIS_REPO.md](docs/ABOUT_THIS_REPO.md).

---

## Disclaimer — showcase vs private product

This repository is a **professional portfolio showcase**, not the product's source code. It reflects a real, actively developed career intelligence platform, with the following boundaries:

- **No proprietary implementation.** Acquisition adapters, AI scoring/ranking, persistence, and operational automation are private.
- **No credentials or live data.** Nothing in this repository requires or includes API keys, session tokens, or real user data.
- **AI scores are advisory** in the underlying product — not hiring decisions, and always subject to verification against the original listing.
- **The live demo is a sandbox.** It's real software running against anonymized, representative data — not the production database.

For interview or portfolio context: emphasize **orchestration**, **incremental memory**, **explainable AI**, **Demo Mode as a product boundary**, and **operator-grade observability** — not raw scrape volume.

---

## License

See [LICENSE](LICENSE).
