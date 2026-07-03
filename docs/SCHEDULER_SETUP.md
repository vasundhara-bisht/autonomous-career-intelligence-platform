# Scheduler setup (macOS production)

**Status:** Task 3 scheduler activation **complete** (2026-06-23). **OHM Phases 1–6 complete** (2026-06-25): lifecycle monitor LaunchAgent **re-enabled** at **17:00 IST once daily** with governance limits (`data/ohm_signoff.json`). **OHM Phase 2 (2026-06-25):** provider protection detection + `monitor_provider_state` persistence; mid-run LinkedIn abort on protection pages (no per-job `check_failed` spam).

**Canonical reference** for production scheduling install, configuration, logs, and uninstall on the private repo. The scheduler is a **first-class platform capability**: it lives outside `main.py` and invokes the existing pipeline unchanged (D8B SQLite defaults, default `*_MAX_RUNS` caps, no `SQLITE_*` exports).

**Schedule (current production):**

| Job | Local time | Script |
|-----|------------|--------|
| Acquisition + parity | **09:00** and **21:00** IST daily | `scripts/scheduling/run_scheduled_acquisition.sh` |
| Lifecycle monitor (Scheduler B) | **17:00** IST once daily | `scripts/scheduling/run_scheduled_lifecycle_monitor.sh` |
| Backup (optional) | **Sunday 23:00** IST | `scripts/scheduling/run_scheduled_backup.sh` |

**Historical (Task 3, pre-OHM):** lifecycle monitor ran at **13:00** and **01:00** IST twice daily until paused for Operational Hardening.

**Source of truth for times:** plist templates under `scripts/scheduling/launchd/` (`StartCalendarInterval`). Installed plists under `~/Library/LaunchAgents/` must match templates after `install_launchagents.sh`.

**Task 3 activation runbook:** SCHEDULER_SETUP.md

**Not scheduled:** Streamlit dashboard (manual review). Launch with **`./scripts/run_dashboard.sh`** (loads `.env` like scheduler wrappers).

### Dashboard (manual review)

```bash
cd ~/Desktop/autonomous-career-intelligence-platform
./scripts/run_dashboard.sh
# Custom port:
# ./scripts/run_dashboard.sh --server.port 8502
```

The launcher sources repo-root `.env` before `streamlit run dashboard/app.py`. Bare `streamlit run` does **not** load `.env`.

---

## Platform role

| Layer | Role |
|-------|------|
| **Product** | Twice-daily acquisition (09:00 / 21:00 IST); lifecycle monitor **17:00 IST once daily**; dashboard review stays human-in-the-loop |
| **Architecture** | External `launchd` → locked shell wrappers → `main.py` or `run_lifecycle_monitor.py`; separate file locks per scheduler |
| **Operational** | Install, logs, parity validation, uninstall — this document |

The scheduler does not alter scoring, acquisition, or persistence logic inside `src/agent/`. Listing availability is tracked via `listing_status` (lifecycle monitor); the legacy inactive sweep was retired in Task 4.

---

## Related documentation

| Doc | Use when you need |
|-----|-------------------|
| [PRODUCTION_OPERATIONS.md](./PRODUCTION_OPERATIONS.md) §3 | Daily workflow, manual fallback, weekly backup |
| [PROJECT_COMMAND_REFERENCE.md](./PROJECT_COMMAND_REFERENCE.md) §10.1, §12 | Script commands and cheat sheet |
| [PRODUCT_STATUS_SUMMARY.md](./PRODUCT_STATUS_SUMMARY.md) §6–§7 | Operating model and limitations |

---

## Public mirror note

`scripts/scheduling/` (shell scripts and plist templates) may be copied to the **public** portfolio repo on promotion. **Operator-local only:** `.env`, `logs/scheduled/`, and installed plists under `~/Library/LaunchAgents/`. Sanitize `docs/SCHEDULER_SETUP.md` on promote (example profile paths) per PUBLIC_REPO.md.

---

## Prerequisites

1. Repository: `~/Desktop/autonomous-career-intelligence-platform` (or your clone path).
2. Virtualenv: `python3 -m venv venv && pip install -r requirements.txt`
3. Playwright: `playwright install chromium` (for LinkedIn / Instahyre).
4. Secrets file: create **`.env`** in repo root (gitignored; production-only, never commit):

   ```bash
   OPENAI_API_KEY=sk-...
   ```

   Scheduled acquisition sets `LINKEDIN_MAX_RUNS=3` in the wrapper (not via `.env`). Manual `python main.py` defaults remain unchanged.

5. Auth: `data/linkedin_auth.json` and `data/instahyre_auth.json` present (scraper login flows).
6. Machine awake and logged in as your macOS user at scheduled times (LaunchAgents run in your GUI session).
7. **Dashboard:** use `./scripts/run_dashboard.sh` (not bare `streamlit run`) so `.env` secrets load.

---

## What each run does

### Acquisition (09:00 / 21:00 IST)

1. Exclusive file lock via [scripts/scheduling/with_file_lock.py](../scripts/scheduling/with_file_lock.py) (`fcntl`) on `/tmp/ai-job-agent-acquisition.lock` — skips if a previous run is still active.
2. `python main.py` — default D8B SQLite flags (no `SQLITE_*` exports); wrapper sets `LINKEDIN_MAX_RUNS=3` (other `*_MAX_RUNS` use code defaults, including Instahyre feeds + **Interested sync** when `INSTAHYRE_MAX_RUNS` is non-zero).
3. `python scripts/validate_sqlite_parity.py --mode production --fail-on-error`

When Instahyre is enabled, scheduled runs include post-feed **Interested synchronization** (list-only Applied-state sync) inside `main.py` — same as manual acquisition. Look for `🟣 INSTAHYRE INTERESTED SYNC SUMMARY` in acquisition logs.

Logs: `logs/scheduled/acquisition-YYYYMMDD-HHMMSS.log` (gitignored).

### Lifecycle monitor (17:00 IST once daily)

1. Probe acquisition lock — **skip exit 0** if acquisition is in progress.
2. Exclusive lock on `/tmp/ai-job-agent-lifecycle-monitor.lock`.
3. `python scripts/run_lifecycle_monitor.py --apply` with OHM Phase 1 defaults from wrapper:
   - `LIFECYCLE_MONITOR_LINKEDIN_MAX_PER_RUN=150` (cohort cap when `--limit` omitted)
   - `LIFECYCLE_MONITOR_JOB_DELAY_SEC=2.0`
   - `LIFECYCLE_MONITOR_BUDGET_TZ=Asia/Kolkata` (daily per-provider budget reset; “Checked Today” on dashboard)
   - Skips all LinkedIn job checks when auth probe is `degraded` or provider protection is detected (OHM Phase 2)
4. `python scripts/validate_lifecycle_monitor_parity.py` (TD9 warning-only; wrapper exits 0 if monitor succeeded).

When the lifecycle LaunchAgent plist is installed, runs fire at **17:00 IST once daily**. OHM Phase 6 re-enable is complete (`data/ohm_signoff.json`); use Operational Controls Pause/Resume or `uninstall_launchagents.sh --lifecycle-only` to change posture.

Logs: `logs/scheduled/lifecycle-monitor-YYYYMMDD-HHMMSS.log` (gitignored).

### Backup (optional, Sunday 23:00)

1. `./scripts/archive_state.sh`
2. `python scripts/export_csv_memory.py --all`
3. `python scripts/validate_sqlite_parity.py --mode source-of-truth --fail-on-error`

Logs: `logs/scheduled/backup-YYYYMMDD-HHMMSS.log`

---

## Install LaunchAgents

```bash
cd ~/Desktop/autonomous-career-intelligence-platform
chmod +x scripts/scheduling/*.sh
./scripts/scheduling/install_launchagents.sh
# Optional weekly backup:
./scripts/scheduling/install_launchagents.sh --with-backup
# Partial install:
# ./scripts/scheduling/install_launchagents.sh --lifecycle-only
```

This copies rendered plists to `~/Library/LaunchAgents/` and runs `launchctl bootstrap` for acquisition **and** lifecycle monitor.

Manual install (without helper script):

```bash
REPO=~/Desktop/autonomous-career-intelligence-platform
sed "s|@REPO_ROOT@|${REPO}|g" \
  scripts/scheduling/launchd/com.vasundhara-bisht.ai-job-agent.acquisition.plist.template \
  > ~/Library/LaunchAgents/com.vasundhara-bisht.ai-job-agent.acquisition.plist
launchctl bootstrap "gui/$(id -u)" \
  ~/Library/LaunchAgents/com.vasundhara-bisht.ai-job-agent.acquisition.plist
```

---

## Manual test (before relying on calendar)

```bash
cd ~/Desktop/autonomous-career-intelligence-platform
./scripts/scheduling/run_scheduled_acquisition.sh
./scripts/scheduling/run_scheduled_lifecycle_monitor.sh
```

Or trigger via launchd:

```bash
launchctl kickstart -k "gui/$(id -u)/com.vasundhara-bisht.ai-job-agent.acquisition"
launchctl kickstart -k "gui/$(id -u)/com.vasundhara-bisht.ai-job-agent.lifecycle-monitor"
```

Confirm new logs under `logs/scheduled/` and `SQLITE DUAL-WRITE SUMMARY` → `success=1` in acquisition logs.

---

## Uninstall / disable

```bash
./scripts/scheduling/uninstall_launchagents.sh
# Lifecycle monitor only (Task 3 rollback):
# ./scripts/scheduling/uninstall_launchagents.sh --lifecycle-only
```

Or manually:

```bash
UID_NUM=$(id -u)
launchctl bootout "gui/${UID_NUM}" \
  ~/Library/LaunchAgents/com.vasundhara-bisht.ai-job-agent.acquisition.plist
launchctl bootout "gui/${UID_NUM}" \
  ~/Library/LaunchAgents/com.vasundhara-bisht.ai-job-agent.lifecycle-monitor.plist
rm -f ~/Library/LaunchAgents/com.vasundhara-bisht.ai-job-agent.*.plist
rm -f /tmp/ai-job-agent-acquisition.lock /tmp/ai-job-agent-lifecycle-monitor.lock /tmp/ai-job-agent-backup.lock
```

Pipeline remains runnable manually: `python main.py`, `python scripts/run_lifecycle_monitor.py --apply`, `python scripts/run_ai_refresh.py --preset discovery`.

### AI refresh (manual-only, v1)

**Refresh AI Evaluations** is **not** wired to launchd in v1. Trigger via dashboard Operator Controls or `python scripts/run_ai_refresh.py`. Uses `/tmp/ai-job-agent-ai-refresh.lock` and defers when acquisition lock is held. Optional future: launchd wrapper parity with acquisition/lifecycle — see [PROJECT_COMMAND_REFERENCE.md](./PROJECT_COMMAND_REFERENCE.md) §10.

---

## Operations

| Topic | Guidance |
|-------|----------|
| **Overlap** | Acquisition and monitor use separate locks. Monitor skips (exit 0) if acquisition lock is held. |
| **Failures** | Inspect latest `logs/scheduled/*.log`; re-run manually after fixing auth/API. |
| **OpenAI cost** | Scales with eligible AI candidates per acquisition run (no per-run cap). |
| **LinkedIn cooldown** | 32h query cooldown — second daily run may score fewer new LinkedIn jobs. |
| **Log rotation** | Prune `logs/scheduled/` periodically (e.g. keep 30 days). |
| **Parity fails on empty DB** | Run one successful `main.py` before expecting `--fail-on-error` to pass. |
| **Parity WARN vs FAIL** | `--fail-on-error` exits **1** only on **strict** failures. |
| **False SKIP (no main.py in log)** | Real overlap shows `SKIP: another acquisition holds` without flock errors. |

---

## LaunchAgent summary

| Label | Calendar | Command |
|-------|----------|---------|
| `com.vasundhara-bisht.ai-job-agent.acquisition` | 09:00, 21:00 IST daily | `run_scheduled_acquisition.sh` |
| `com.vasundhara-bisht.ai-job-agent.lifecycle-monitor` | 17:00 IST once daily | `run_scheduled_lifecycle_monitor.sh` |
| `com.vasundhara-bisht.ai-job-agent.backup` | Sunday 23:00 (optional) | `run_scheduled_backup.sh` |

Templates live under `scripts/scheduling/launchd/*.plist.template` (`@REPO_ROOT@` replaced on install).
