# About this repository

This repository is a **portfolio showcase**, not the product's source code.

The production acquisition engine, AI scoring, prioritization, and operational automation remain private. A live Demo Mode deployment is available here: **`<LIVE_DEMO_URL>`**.

## Why

The product is a real, actively developed system with genuine engineering investment — multi-source job acquisition, AI-driven scoring, recruiter and outreach intelligence, and operational health monitoring. Publishing the full implementation would let anyone clone, study, and rebuild it directly, which works against a product that may be monetized in the future.

Instead, this repository is curated to answer the questions a recruiter, hiring manager, founder, or engineering lead actually asks in the first few minutes of review:

- What problem does this solve, and for whom?
- Is the architecture and AI system design coherent and well-reasoned?
- Can this person actually build production-quality software, not just prototype it?
- What does the finished product look and feel like?

The README, [ARCHITECTURE.md](./ARCHITECTURE.md), [DATA_MODEL.md](./DATA_MODEL.md), [AI_SYSTEM_DESIGN.md](./AI_SYSTEM_DESIGN.md), and diagrams answer the first two. The [Live Demo](./DEMO_MODE.md) answers the last. A small set of standalone code excerpts under [`showcase/`](../showcase/) demonstrate real engineering and UX craftsmanship in isolation, without exposing the proprietary implementation.

## What's intentionally not here

- The multi-source acquisition adapters (LinkedIn, Instahyre, Greenhouse, Lever, Himalayas)
- The AI scoring, ranking, and deduplication/identity implementation
- The recruiter and outreach intelligence implementation
- The persistence layer, migrations, and operational scripts/scheduler
- The full test suite covering that implementation

## How this repository is maintained

Unlike a typical open-source project, this repository is **not** kept in sync file-by-file with the private product. It's refreshed intentionally and occasionally — a new architecture diagram, a new screenshot, a capability worth narrating — not on every private commit. See the private repository's `docs/PORTFOLIO_PUBLISHING.md` (not published) for the maintainer workflow.
