# AI candidate profiles

Canonical candidate identity and preferences for **OpenAI batch scoring** in the job pipeline.

## Default profile (repository)

| File | Purpose |
|------|---------|
| [`ai_candidate_profile.example.md`](ai_candidate_profile.example.md) | Generic example persona for clones, tests, and public repos |

Resolved by [`paths.ai_candidate_profile_path()`](../../src/paths.py) unless overridden.

## Your own profile (local only)

Copy the example to a new markdown file (e.g. `config/profiles/my_candidate_profile.md`), add your real preferences, and **do not commit** it if it contains PII.

## Environment override

```bash
export AI_CANDIDATE_PROFILE_PATH=config/profiles/my_candidate_profile.md
python main.py
```

Path may be absolute or relative to the repository root.

## What belongs in the profile file

- Professional summary, target roles, industries, location preferences
- Positive and negative scoring signals
- Domain strengths (fintech, platform, AI product, etc.)

## What stays in code (do not duplicate in markdown)

- Scoring instructions, JSON output format, seniority accept/reject rules
- Model choice and batching behavior

Those live in [`src/agent/ai_batch_scorer.py`](../../src/agent/ai_batch_scorer.py).

## Editing workflow

1. **Fresh clone:** edit `ai_candidate_profile.example.md`, or set `AI_CANDIDATE_PROFILE_PATH` to your own markdown file (see [docs/CLONE_SETUP.md](../../docs/CLONE_SETUP.md)).
2. **Daily use:** edit your local profile file and export `AI_CANDIDATE_PROFILE_PATH` before `python main.py`.
3. Run acquisition — profile is loaded once at the start of AI scoring.
4. Terminal logs show path and character count, e.g. `Candidate profile: ... (4177 chars)`.

## Token impact

A full profile is often ~4,000+ characters (~1,000 tokens) per batch request, in addition to job descriptions and the fixed instruction block. Shorter profiles reduce cost; longer profiles improve fit specificity.

## Portfolio / public repos

The committed default is the example file only. See [docs/PUBLIC_REPO.md](../../docs/PUBLIC_REPO.md) (maintainers).

## Related docs

- [docs/PRODUCTION_OPERATIONS.md](../../docs/PRODUCTION_OPERATIONS.md) — AI scoring configuration
- [docs/PRODUCT_STATUS_SUMMARY.md](../../docs/PRODUCT_STATUS_SUMMARY.md) — profile overview
