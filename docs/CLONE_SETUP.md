# Clone setup (public repository)

Step-by-step guide for running this **portfolio-safe** clone on a fresh machine. For product context, start with [PRODUCT_STATUS_SUMMARY.md](./PRODUCT_STATUS_SUMMARY.md) and the root [README.md](../README.md).

## 1. Clone and Python environment

```bash
git clone https://github.com/vasundhara-bisht/autonomous-career-intelligence-platform.git
cd autonomous-career-intelligence-platform
python3 -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
```

## 2. Environment variables

```bash
cp .env.example .env
# Edit .env and set OPENAI_API_KEY=sk-...
```

Alternatively export in your shell before each run.

## 3. Initialize SQLite schema

```bash
python scripts/db_init.py
```

Creates `data/ai_job_agent.db` with Alembic migrations. The `data/` directory is gitignored except `.gitkeep`.

## 4. Candidate profile

The default scoring profile is [`config/profiles/ai_candidate_profile.example.md`](../config/profiles/ai_candidate_profile.example.md) (fictional **Alex Morgan** persona).

- Edit that file for local experiments, **or**
- Copy it to a new markdown file and set `AI_CANDIDATE_PROFILE_PATH` in `.env`.

See [config/profiles/README.md](../config/profiles/README.md) for what belongs in the profile (preferences/signals only — not the scorer prompt).

## 5. LinkedIn and Instahyre (optional)

This clone ships **placeholder** job IDs in `config/linkedin_queries.json`. Before live LinkedIn acquisition:

1. Replace placeholders with your own query catalog and a current Top Applicant `landing_url` when ready.
2. Create session files under `data/` via the scraper login flows (never commit them):
   - `data/linkedin_auth.json`
   - `data/instahyre_auth.json`

Set `LINKEDIN_MAX_RUNS=0` or `INSTAHYRE_MAX_RUNS=0` to skip sources you have not configured.

## 6. First pipeline run

Start with conservative caps while validating setup:

```bash
export OPENAI_API_KEY="..."   # if not using .env
export DEBUG_LIMIT=10           # optional: limit AI spend on first run
python main.py
```

Expect SQLite dual-write logs and optional `jobs.csv` export under `data/` per default flags in `src/db/config.py`.

Post-run health check:

```bash
python scripts/validate_sqlite_parity.py --mode production --fail-on-error
```

## 7. Dashboard

```bash
streamlit run dashboard/app.py
```

Sidebar should indicate SQLite as the data source when defaults are on.

## 8. Tests (optional)

```bash
python -m unittest discover -s tests -p 'test_*.py'
```

Some persistence tests may fail on an empty database until you have run acquisition at least once.

## 9. What stays local

Never commit:

- `data/ai_job_agent.db`, CSV exports, auth JSON, query state
- `logs/`, `venv/`, personal profile copies with real PII
- `archive/` snapshots containing real hiring data

Maintainers updating this public mirror: see [PUBLIC_REPO.md](./PUBLIC_REPO.md).
