#!/usr/bin/env bash
# Runs under with_file_lock.py — do not invoke directly.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
PYTHON="${AI_JOB_AGENT_PYTHON:-$ROOT/venv/bin/python}"

echo ""
echo "--- run_lifecycle_monitor.py --apply ($(date -Iseconds)) ---"
export LIFECYCLE_MONITOR_JOB_DELAY_SEC="${LIFECYCLE_MONITOR_JOB_DELAY_SEC:-2.0}"
export LIFECYCLE_MONITOR_LINKEDIN_MAX_PER_RUN="${LIFECYCLE_MONITOR_LINKEDIN_MAX_PER_RUN:-150}"
export LIFECYCLE_MONITOR_LINKEDIN_MAX_PER_DAY="${LIFECYCLE_MONITOR_LINKEDIN_MAX_PER_DAY:-150}"
export LIFECYCLE_MONITOR_INSTAHYRE_MAX_PER_RUN="${LIFECYCLE_MONITOR_INSTAHYRE_MAX_PER_RUN:-500}"
export LIFECYCLE_MONITOR_INSTAHYRE_MAX_PER_DAY="${LIFECYCLE_MONITOR_INSTAHYRE_MAX_PER_DAY:-500}"
set +e
"$PYTHON" scripts/run_lifecycle_monitor.py --apply
MONITOR_EXIT=$?
set -e

echo ""
echo "--- validate_lifecycle_monitor_parity.py (TD9 warning-only) ($(date -Iseconds)) ---"
set +e
"$PYTHON" scripts/validate_lifecycle_monitor_parity.py
PARITY_EXIT=$?
set -e

echo ""
echo "============================================================"
echo "Scheduled lifecycle monitor finished: $(date -Iseconds)"
echo "monitor exit=$MONITOR_EXIT parity exit=$PARITY_EXIT"
echo "============================================================"

# TD9: wrapper exits 0 when monitor succeeds regardless of parity warnings.
if [[ "$MONITOR_EXIT" -ne 0 ]]; then
  exit "$MONITOR_EXIT"
fi
exit 0
