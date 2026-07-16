# AI system design

How AI scoring fits into the pipeline, and the design decisions behind it. The actual prompt, weighting, and batching implementation are proprietary and not published; this document explains the approach and the guardrails around it.

## What the model evaluates

Each job is scored against an external, editable candidate profile — not a hardcoded set of keywords. See [`config/profiles/README.md`](../config/profiles/README.md) and the public example profile, [`config/profiles/ai_candidate_profile.example.md`](../config/profiles/ai_candidate_profile.example.md), for the shape of that input.

The model is asked to reason about:

- **Domain fit** — e.g. fintech, B2B SaaS, AI/ML, against the profile's stated target domains
- **Responsibility signals from the full job description**, not the title alone — a "Senior Product Manager" title can mean very different jobs
- **Seniority alignment** against explicit profile constraints
- **Explicit rejection rules** — e.g. staff/principal/director-scoped roles are down-ranked when the profile says so, regardless of how well the domain matches

## Output contract

Every scored job returns exactly two things:

| Field | Meaning |
|-------|---------|
| `score` | A numeric fit score |
| `reason` | A short, specific explanation referencing domain, responsibility, and seniority fit |

**Explainability is a hard requirement, not a nice-to-have.** A ranked list without a reason attached is not something a reviewer (human or, here, a hiring manager reading this repo) can trust or act on quickly.

## Batching and cost control

Jobs are scored in batches rather than one API call per job, both for cost efficiency and to keep run time predictable as acquisition volume grows. Layered relevance filtering (see [ARCHITECTURE.md](./ARCHITECTURE.md)) runs *before* AI scoring specifically so the batch only contains plausible candidates — the AI budget is not spent scoring obviously irrelevant listings.

## Calibration discipline

Below are qualitative calibration patterns used to sanity-check scoring behavior — illustrative, not the production prompt or scoring weights:

### Example A — Strong fit (high score band)
*Senior Product Manager, Payments Platform.* Positives: clear end-to-end ownership of payment workflows, roadmap and stakeholder management, domain match. No significant penalties. Reads as a strong fit.

### Example B — Partial fit (mid score band)
*Senior Product Manager, Developer Tools, 7-8 years.* Positives: solid PM ownership, roadmap, cross-functional delivery. Penalties: mild seniority stretch, domain adjacent rather than exact. Worth a human review, not an auto-reject.

### Example C — Poor fit (low score band)
*Product Manager, Oncology Marketing.* No significant positives: brand/marketing function in pharma, not technology product ownership. Reads as fundamentally outside the target profile.

The point of keeping calibration examples like these is that scoring behavior should be *testable against intent* — "does this match what I actually meant by the profile" — not just internally consistent.

## Guardrails

- Seniority ceilings are enforced explicitly, not left to the model's judgment alone.
- Scores are always paired with a reason string; there is no code path that persists a bare numeric score.
- Re-scoring (AI refresh) is a distinct, auditable operation — not a silent overwrite of prior evaluations.
