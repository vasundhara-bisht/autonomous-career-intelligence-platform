#!/usr/bin/env bash
# Weekly backup: archive runtime state, export CSV memory, source-of-truth parity.
# Optional launchd job (Sunday 23:00). See docs/SCHEDULER_SETUP.md.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

LOCK_FILE="${AI_JOB_AGENT_BACKUP_LOCK_FILE:-/tmp/ai-job-agent-backup.lock}"
LOG_DIR="$ROOT/logs/scheduled"
STAMP="$(date +%Y%m%d-%H%M%S)"
LOG_FILE="$LOG_DIR/backup-${STAMP}.log"
PYTHON="${AI_JOB_AGENT_PYTHON:-$ROOT/venv/bin/python}"

mkdir -p "$LOG_DIR"
exec >>"$LOG_FILE" 2>&1

echo "============================================================"
echo "Scheduled backup started: $(date -Iseconds)"
echo "ROOT=$ROOT"
echo "LOG_FILE=$LOG_FILE"
echo "============================================================"

if [[ ! -x "$PYTHON" ]]; then
  echo "ERROR: Python not found at $PYTHON"
  exit 1
fi

SKIP_MSG="SKIP: another backup holds $LOCK_FILE ($(date -Iseconds))"
exec "$PYTHON" scripts/scheduling/with_file_lock.py \
  --lock-file "$LOCK_FILE" \
  --skip-exit 0 \
  --skip-message "$SKIP_MSG" \
  --cwd "$ROOT" \
  -- \
  bash "${ROOT}/scripts/scheduling/_backup_locked_body.sh"
