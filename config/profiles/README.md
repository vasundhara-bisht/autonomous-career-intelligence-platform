# AI candidate profiles

Canonical candidate identity and preferences for **OpenAI batch scoring** in the job pipeline.

## Default profile

| File | Purpose |
|------|---------|
| [`ai_candidate_profile_v2.md`](ai_candidate_profile_v2.md) | Production profile (target roles, industries, positive/negative signals) |

Resolved by [`paths.ai_candidate_profile_path()`](../../src/paths.py) unless overridden.

## Environment override

```bash
export AI_CANDIDATE_PROFILE_PATH=config/profiles/my_variant.md
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

1. Edit `ai_candidate_profile_v2.md` (or your override path).
2. Run acquisition — profile is loaded once at the start of AI scoring.
3. Terminal logs show path and character count, e.g. `Candidate profile: ... (4177 chars)`.

## Token impact

The v2 profile is ~4,000+ characters (~1,000 tokens) per batch request, in addition to job descriptions and the fixed instruction block. Shorter profiles reduce cost; longer profiles improve fit specificity.

## Portfolio / public repos

Replace personal data before publishing. Use a generic example profile or omit the file and document `AI_CANDIDATE_PROFILE_PATH` in [docs/PUBLIC_REPO.md](../../docs/PUBLIC_REPO.md).

## Related docs

- [docs/PRODUCTION_OPERATIONS.md](../../docs/PRODUCTION_OPERATIONS.md) §5 — AI scoring configuration
- [docs/PRODUCT_STATUS_SUMMARY.md](../../docs/PRODUCT_STATUS_SUMMARY.md) §5 — profile overview
