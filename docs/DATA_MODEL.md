# Data model (high level)

The product's memory is a relational database (SQLite in the current deployment, managed with SQLAlchemy models and Alembic migrations). This document describes the *categories* of state it tracks and why — not the column-level schema or migration history, which are part of the private implementation.

## Why a persistent store, not stateless batch runs

A career-intelligence pipeline that re-evaluates every job from scratch on every run is slow, expensive (repeated AI calls), and has no memory of relationships (recruiters, outreach, application stage) that build up over time. The data model exists to make each run **incremental**: recognize what's already known, only do new work on what's actually new or changed.

## Table categories

| Category | What it tracks | Why it matters |
|----------|------------------|-----------------|
| **Jobs** | Normalized listings with a stable identity, source, and current lifecycle status (open/closed/removed) | The unit of the whole system; identity resolution here is what makes dedup and incremental runs possible |
| **Evaluations** | AI score + explanation per job, with a history of re-scoring runs | Keeps scoring auditable and explainable, not a single overwritten value |
| **Descriptions** | Full job text fetched separately from the listing summary | Scoring quality depends on full text, not just title/snippet |
| **Recruiters** | Hiring-contact identity and relationship stage over time | Turns "a listing" into "a relationship with a person," tracked across multiple jobs |
| **Outreach records** | Attempted/sent outreach, follow-up state, linked hiring signals | A CRM-style log distinct from the recruiter relationship itself |
| **Company catalog** | Known companies and their ATS presence, used to drive acquisition coverage | Lets the system expand acquisition coverage deliberately rather than only reacting to inbound listings |
| **Acquisition runs** | Per-source run history, counts, and outcomes | Operational visibility into what each pipeline run actually did |
| **Monitor runs** | Listing-lifecycle health checks (still open? closed? applied?) | Keeps listing status current between full acquisition runs |

## Design choices worth calling out

- **Dual identity model.** Jobs carry both a legacy derived key (title + company) and a source-aware opaque ID (native ID, canonical URL, or hash fallback), tagged with a confidence tier. This let the identity model evolve without breaking historical continuity.
- **Migration discipline.** Schema changes go through versioned migrations rather than ad-hoc table edits, so the database can evolve safely across a long-running, continuously-operated system.
- **Read/write separation.** Read paths are optimized for dashboard consumption (views, aggregates); write paths enforce the business rules for what's allowed to overwrite what (e.g. a hiring-manager field should not be blanked by a later re-scrape that failed to find one).

The full schema, migration history, and read/write service implementation are part of the private repository.
