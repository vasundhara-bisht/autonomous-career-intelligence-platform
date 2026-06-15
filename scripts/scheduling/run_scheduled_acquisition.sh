#!/usr/bin/env bash
# Scheduled acquisition + production parity validation (private production).
# Invoked by launchd at 10:00 and 21:00 IST. See docs/SCHEDULER_SETUP.md.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

LOCK_FILE="${AI_JOB_AGENT_LOCK_FILE:-/tmp/ai-job-agent-acquisition.lock}"
LOG_DIR="$ROOT/logs/scheduled"
STAMP="$(date +%Y%m%d-%H%M%S)"
LOG_FILE="$LOG_DIR/acquisition-${STAMP}.log"
PYTHON="${AI_JOB_AGENT_PYTHON:-$ROOT/venv/bin/python}"

mkdir -p "$LOG_DIR"
exec >>"$LOG_FILE" 2>&1

echo "============================================================"
echo "Scheduled acquisition started: $(date -Iseconds)"
echo "ROOT=$ROOT"
echo "LOG_FILE=$LOG_FILE"
echo "============================================================"

if [[ ! -x "$PYTHON" ]]; then
  echo "ERROR: Python not found at $PYTHON (create venv: python3 -m venv venv && pip install -r requirements.txt)"
  exit 1
fi

if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
  echo "Loaded environment from $ROOT/.env"
fi

if [[ -z "${OPENAI_API_KEY:-}" ]]; then
  echo "ERROR: OPENAI_API_KEY is not set. Add it to $ROOT/.env or export before scheduling."
  exit 1
fi

export AI_CANDIDATE_PROFILE_PATH="${AI_CANDIDATE_PROFILE_PATH:-config/profiles/ai_candidate_profile_v2.md}"
unset LINKEDIN_QUALIFICATION_LANDING_URL || true
export LINKEDIN_MAX_RUNS=3
echo "Scheduler cap: LINKEDIN_MAX_RUNS=3"

SKIP_MSG="SKIP: another acquisition holds $LOCK_FILE ($(date -Iseconds))"
exec "$PYTHON" scripts/scheduling/with_file_lock.py \
  --lock-file "$LOCK_FILE" \
  --skip-exit 0 \
  --skip-message "$SKIP_MSG" \
  --cwd "$ROOT" \
  -- \
  bash "${ROOT}/scripts/scheduling/_acquisition_locked_body.sh"
