# AI candidate profiles

Canonical candidate identity and preferences used as the input to AI batch scoring in the production pipeline.

## Default profile

| File | Purpose |
|------|---------|
| [`ai_candidate_profile.example.md`](ai_candidate_profile.example.md) | Generic example profile shipped in this repository |

The production deployment uses a private, personal profile in the same format; this example illustrates the shape of that input without exposing personal data.

Outreach message signoff is derived from the active profile (or an environment override) rather than hardcoded — see [docs/AI_SYSTEM_DESIGN.md](../../docs/AI_SYSTEM_DESIGN.md).

Qualitative calibration examples (few-shot patterns used to sanity-check scoring behavior) live in [`../ai_scoring_calibration_examples.md`](../ai_scoring_calibration_examples.md).

## What belongs in the profile file

- Professional summary, target roles, industries, location preferences
- Positive and negative scoring signals (gradual decrease language)
- Domain strengths (fintech, platform, AI product, etc.)
- Non-target role types (hard-reject taxonomy)

## What stays in code (private implementation)

The actual scoring prompt, JSON output format, model choice, and batching behavior are part of the private implementation — see [docs/AI_SYSTEM_DESIGN.md](../../docs/AI_SYSTEM_DESIGN.md) for the design rationale without the implementation itself.

## Using a different profile

If you're exploring this repository's `showcase/` excerpts, the candidate-profile concept isn't wired into any runnable code here — it's part of the private scoring pipeline. This file documents the *format*, not a runnable override.
