# Public mirror (maintainers)

This repository is the **portfolio-safe** copy of the Autonomous Career Intelligence Platform.

| Audience | Start here |
|----------|------------|
| Cloners / reviewers | [CLONE_SETUP.md](./CLONE_SETUP.md), root [README.md](../README.md) |
| Product snapshot | [PRODUCT_STATUS_SUMMARY.md](./PRODUCT_STATUS_SUMMARY.md) |

## Promoting updates

Sync from the private production repository using the internal Option A promotion workflow (rsync, overlays, PII grep gates, doc sanitization). Do not copy `data/`, auth JSON, personal profiles, or operator log artifacts into this tree.

## Pre-push checklist

1. `git status` — no tracked files under `data/` except `.gitkeep`.
2. Grep staged files for API keys, emails, phone numbers, and real LinkedIn job/session IDs.
3. Confirm `config/profiles/` contains only the example persona (or sanitized copies).
4. Run `python scripts/db_init.py` and `python -m unittest discover -s tests` on the public clone before the first push.
