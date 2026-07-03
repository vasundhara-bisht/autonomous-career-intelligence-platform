#!/usr/bin/env bash
# Manual operator lifecycle monitor — skips operator pause; scheduled path unchanged.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

ACQUISITION_LOCK="${AI_JOB_AGENT_ACQUISITION_LOCK_FILE:-/tmp/ai-job-agent-acquisition.lock}"
LIFECYCLE_LOCK="${AI_JOB_AGENT_LIFECYCLE_LOCK_FILE:-/tmp/ai-job-agent-lifecycle-monitor.lock}"
LOG_DIR="$ROOT/logs/manual"
STAMP="$(date +%Y%m%d-%H%M%S)"
LOG_FILE="${LIFECYCLE_MONITOR_LOG_FILE:-$LOG_DIR/lifecycle-monitor-${STAMP}.log}"
PYTHON="${AI_JOB_AGENT_PYTHON:-$ROOT/venv/bin/python}"

mkdir -p "$LOG_DIR"
exec >>"$LOG_FILE" 2>&1

echo "============================================================"
echo "Manual lifecycle monitor started: $(date -Iseconds)"
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

export SQLITE_ENABLED="${SQLITE_ENABLED:-1}"
export LIFECYCLE_MONITOR_RUN_TRIGGER=manual
echo "Run trigger: LIFECYCLE_MONITOR_RUN_TRIGGER=manual"

ACQ_SKIP_MSG="SKIP: acquisition in progress, lifecycle monitor deferred ($(date -Iseconds))"
if ! "$PYTHON" scripts/scheduling/probe_file_lock.py \
  --lock-file "$ACQUISITION_LOCK" \
  --skip-message "$ACQ_SKIP_MSG"; then
  echo "$ACQ_SKIP_MSG"
  echo "============================================================"
  echo "Manual lifecycle monitor skipped (acquisition lock held): $(date -Iseconds)"
  echo "============================================================"
  exit 0
fi

SKIP_MSG="SKIP: another lifecycle monitor holds $LIFECYCLE_LOCK ($(date -Iseconds))"
exec "$PYTHON" scripts/scheduling/with_file_lock.py \
  --lock-file "$LIFECYCLE_LOCK" \
  --skip-exit 0 \
  --skip-message "$SKIP_MSG" \
  --cwd "$ROOT" \
  -- \
  bash "${ROOT}/scripts/scheduling/_lifecycle_monitor_locked_body.sh"
