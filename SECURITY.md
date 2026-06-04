# Security Policy

## Supported versions

This repository is a portfolio reference implementation. Security fixes are applied on a best-effort basis in the maintainer's private production copy and promoted to this public mirror when relevant.

## Reporting a vulnerability

If you discover a security issue in this codebase:

1. **Do not** open a public GitHub issue with exploit details.
2. Email the repository owner via the contact method on their GitHub profile, or use GitHub's private vulnerability reporting if enabled for this repository.
3. Include a clear description, reproduction steps, and impact assessment.

## Scope notes

- **Secrets:** Never commit API keys, session cookies, or auth JSON under `data/`. Use `.env` locally (see `.env.example`).
- **Scraping:** Respect third-party site terms, rate limits, and applicable law. This project is for personal/educational use.
- **Data:** Runtime databases and CSV exports under `data/` are gitignored and remain on your machine only.

We aim to acknowledge reports within a reasonable timeframe and will coordinate disclosure after a fix or documented mitigation.
