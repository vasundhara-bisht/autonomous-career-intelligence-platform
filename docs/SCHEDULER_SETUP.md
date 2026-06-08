# Scheduler setup (macOS, optional)

**Reference** for optional macOS production scheduling: install, configuration, logs, and uninstall. The scheduler is a **first-class platform capability**: it lives outside `main.py` and invokes the existing pipeline unchanged (D8B SQLite defaults, default `*_MAX_RUNS` caps, no `SQLITE_*` exports).

**Schedule (example):**

| Job | Local time | Script |
|-----|------------|--------|
| Acquisition + parity | **07:00** and **19:00** daily | `scripts/scheduling/run_scheduled_acquisition.sh` |
| Backup (optional) | **Sunday 23:00** | `scripts/scheduling/run_scheduled_backup.sh` |

**Not scheduled:** Streamlit dashboard (manual review). See [PRODUCTION_OPERATIONS.md](./PRODUCTION_OPERATIONS.md) §3.

---

## Platform role

| Layer | Role |
|-------|------|
| **Product** | Twice-daily automated job discovery (07:00 / 19:00); dashboard review stays human-in-the-loop |
| **Architecture** | External `launchd` → `run_scheduled_acquisition.sh` → `with_file_lock.py` (fcntl) → `main.py` → SQLite dual-write; one `acquisition_runs` row per pipeline run; file lock prevents concurrent writers |
| **Operational** | Install, logs, parity validation, uninstall — this document |

The scheduler does not alter scoring, acquisition, or persistence logic inside `src/agent/`.

---

## Related documentation

| Doc | Use when you need |
|-----|-------------------|
| [PRODUCTION_OPERATIONS.md](./PRODUCTION_OPERATIONS.md) §3 | Daily workflow, manual fallback, weekly backup |
| [PROJECT_COMMAND_REFERENCE.md](./PROJECT_COMMAND_REFERENCE.md) §10, §12 | Script commands and cheat sheet |
| [PRODUCT_STATUS_SUMMARY.md](./PRODUCT_STATUS_SUMMARY.md) §8–§9 | Operating model and limitations |
| [CLONE_SETUP.md](./CLONE_SETUP.md) | Fresh clone install and first run |

---

## Operator-local artifacts

**Never commit:** `.env`, `logs/scheduled/*`, or installed plists under `~/Library/LaunchAgents/`. These stay on your machine only.

---

## Prerequisites

1. Repository: your clone path (e.g. where you ran `git clone`).
2. Virtualenv: `python3 -m venv venv && pip install -r requirements.txt`
3. Playwright: `playwright install chromium` (for LinkedIn / Instahyre).
4. Secrets file: create **`.env`** in repo root (gitignored; never commit):

   ```bash
   OPENAI_API_KEY=sk-...
   # Optional:
   # AI_CANDIDATE_PROFILE_PATH=config/profiles/ai_candidate_profile.example.md
   ```

   Scheduled runs set `LINKEDIN_MAX_RUNS=3` in the acquisition wrapper (not via `.env`). Manual `python main.py` defaults remain unchanged.

5. Auth: `data/linkedin_auth.json` and `data/instahyre_auth.json` present (scraper login flows).
6. Machine awake and logged in as your macOS user at scheduled times (LaunchAgents run in your GUI session).

---

## What each run does

### Acquisition (07:00 / 19:00)

1. Exclusive file lock via [scripts/scheduling/with_file_lock.py](../scripts/scheduling/with_file_lock.py) (`fcntl`) on `/tmp/ai-job-agent-acquisition.lock` — skips if a previous run is still active.
2. `python main.py` — default D8B SQLite flags (no `SQLITE_*` exports); wrapper sets `LINKEDIN_MAX_RUNS=3` (other `*_MAX_RUNS` use code defaults).
3. `python scripts/validate_sqlite_parity.py --mode production --fail-on-error`

Logs: `logs/scheduled/acquisition-YYYYMMDD-HHMMSS.log` (gitignored).

### Backup (optional, Sunday 23:00)

1. `./scripts/archive_state.sh`
2. `python scripts/export_csv_memory.py --all`
3. `python scripts/validate_sqlite_parity.py --mode source-of-truth --fail-on-error`

Logs: `logs/scheduled/backup-YYYYMMDD-HHMMSS.log`

---

## Install LaunchAgents

```bash
cd /path/to/your-clone
chmod +x scripts/scheduling/*.sh
./scripts/scheduling/install_launchagents.sh
# Optional weekly backup:
./scripts/scheduling/install_launchagents.sh --with-backup
```

This copies rendered plists to `~/Library/LaunchAgents/` and runs `launchctl bootstrap`.

Manual install (without helper script):

```bash
REPO=/path/to/your-clone
sed "s|@REPO_ROOT@|${REPO}|g" \
  scripts/scheduling/launchd/com.vasundhara-bisht.ai-job-agent.acquisition.plist.template \
  > ~/Library/LaunchAgents/com.vasundhara-bisht.ai-job-agent.acquisition.plist
launchctl bootstrap "gui/$(id -u)" \
  ~/Library/LaunchAgents/com.vasundhara-bisht.ai-job-agent.acquisition.plist
```

---

## Manual test (before relying on calendar)

```bash
cd /path/to/your-clone
./scripts/scheduling/run_scheduled_acquisition.sh
```

Or trigger via launchd:

```bash
launchctl kickstart -k "gui/$(id -u)/com.vasundhara-bisht.ai-job-agent.acquisition"
```

Confirm a new log under `logs/scheduled/` and `SQLITE DUAL-WRITE SUMMARY` → `success=1` in the log.

---

## Uninstall / disable

```bash
UID_NUM=$(id -u)
launchctl bootout "gui/${UID_NUM}" \
  ~/Library/LaunchAgents/com.vasundhara-bisht.ai-job-agent.acquisition.plist
rm -f ~/Library/LaunchAgents/com.vasundhara-bisht.ai-job-agent.acquisition.plist
# If backup was installed:
launchctl bootout "gui/${UID_NUM}" \
  ~/Library/LaunchAgents/com.vasundhara-bisht.ai-job-agent.backup.plist 2>/dev/null || true
rm -f ~/Library/LaunchAgents/com.vasundhara-bisht.ai-job-agent.backup.plist
rm -f /tmp/ai-job-agent-acquisition.lock /tmp/ai-job-agent-backup.lock
```

Pipeline remains runnable manually: `python main.py`.

---

## Operations

| Topic | Guidance |
|-------|----------|
| **Overlap** | If morning run exceeds 12h, evening run exits 0 with SKIP (lock). Check logs. |
| **Failures** | Inspect latest `logs/scheduled/acquisition-*.log`; re-run manually after fixing auth/API. |
| **OpenAI cost** | Up to `DEBUG_LIMIT=300` scores per run; evening run is usually smaller on a warm DB. |
| **LinkedIn cooldown** | 32h query cooldown — second daily run may score fewer new LinkedIn jobs; Instahyre/ATS still add value. |
| **Log rotation** | Prune `logs/scheduled/` periodically (e.g. keep 30 days). |
| **Parity fails on empty DB** | Run one successful `main.py` before expecting `--fail-on-error` to pass. |
| **Parity WARN vs FAIL** | `--fail-on-error` exits **1** only on **strict** failures. Stale optional `historical_jobs.csv` keys (default `SQLITE_EXPORT_HISTORICAL_CSV=0`) are **warnings** — scheduler can still report `parity exit=0` when DB HEALTH and OPERATIONAL PASS. |
| **False SKIP (no main.py in log)** | Older wrappers used `/usr/bin/flock`, which macOS lacks; upgrade to `with_file_lock.py`. Real overlap shows `SKIP: another acquisition holds` without a flock “No such file” error. Lock errors exit non-zero. |

---

## LaunchAgent summary

| Label | Calendar | Command |
|-------|----------|---------|
| `com.vasundhara-bisht.ai-job-agent.acquisition` | 07:00, 19:00 daily | `run_scheduled_acquisition.sh` |
| `com.vasundhara-bisht.ai-job-agent.backup` | Sunday 23:00 (optional) | `run_scheduled_backup.sh` |

Templates live under `scripts/scheduling/launchd/*.plist.template` (`@REPO_ROOT@` replaced on install).
