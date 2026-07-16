# Architecture

High-level system design. This is deliberately narrative — it explains *what* the system does and *why* it's structured this way, without pointing into the (unpublished) implementation.

## System overview

![System Architecture](../diagrams/architecture-diagram.png)

The platform follows a single governed path from fragmented job listings to actionable, explainable recommendations:

1. **Multi-source acquisition** — roles are pulled from several hiring channels (job boards, ATS platforms, niche marketplaces) under per-source run controls, so no single source's downtime or rate limits stall the pipeline.
2. **Normalization + identity** — every job is reduced to a stable identity (title, company, source-specific ID or canonical URL) so the same role seen twice — on different sources, or on a re-run — is recognized as one job, not two.
3. **Deduplication** — an ordered strategy (exact source ID, exact application link, then fuzzy title/company matching with seniority guardrails) collapses near-duplicates before expensive downstream work happens.
4. **Layered filtering** — cheap relevance checks run before description fetch and AI scoring, so the AI budget is spent on plausible candidates, not the full firehose of raw listings.
5. **AI scoring** — full job text is evaluated in batches against a candidate profile, producing a fit score and a short, explainable reason (see [AI_SYSTEM_DESIGN.md](./AI_SYSTEM_DESIGN.md)).
6. **Product memory** — a persistent store tracks jobs, evaluations, recruiter relationships, and outreach history across runs, so the system gets incrementally smarter rather than re-processing everything each time (see [DATA_MODEL.md](./DATA_MODEL.md)).
7. **Recruiter + outreach intelligence** — where sources expose hiring-contact metadata, it's captured and tracked as a relationship over time, not just a listing attribute.
8. **Operational health** — acquisition runs, AI refresh cycles, and listing-lifecycle monitoring are all observable, with dashboard surfaces summarizing run history and health rather than requiring log spelunking.
9. **Dashboard** — a Streamlit surface presents ranked recommendations, pipeline analytics, recruiter/outreach intelligence, and operational health in one place.

## Pipeline flow

![End-to-End Pipeline Flow](../diagrams/pipeline_flow.png)

Typical routing:

- **Brand new job** → relevance filter → dedup → description fetch → AI scoring queue
- **Job seen before, not yet AI-scored** → joins the AI queue directly, skipping repeat filtering/dedup/fetch
- **Fully processed job** → merged from memory without re-scoring, unless a refresh is explicitly triggered

This incremental routing is what keeps repeat runs fast and cheap rather than reprocessing the entire universe of jobs every time.

## Design principles

- **Explainability over black-box ranking.** Every AI score ships with a short, human-readable reason. A shortlist you can't explain isn't useful to act on.
- **Memory over stateless batch jobs.** The system's value compounds because it remembers what it has already seen, scored, and tracked — not because each run starts from zero.
- **Layered cost control.** Cheap heuristics gate expensive operations (browser automation, AI calls) so the system stays economical to run continuously.
- **Operational visibility as a first-class concern.** Acquisition and monitoring health are dashboard surfaces, not just logs — because a system that runs unattended needs to be observable.
- **A sandboxed Demo Mode as a product boundary**, not an afterthought — every automation/external-API path is gated through a single policy decision (see [DEMO_MODE.md](./DEMO_MODE.md)), so a public demo can exist safely alongside a private production system.

## What is and isn't in this repository

The diagrams and narrative above describe the full production architecture. The acquisition adapters, scoring/ranking implementation, persistence layer, and operational tooling that realize it are private — see [ABOUT_THIS_REPO.md](./ABOUT_THIS_REPO.md). [`showcase/`](../showcase/) contains a small number of standalone excerpts (a UI component, a policy-gating example, and an illustrative acquisition-adapter pattern) kept for code-quality review.
