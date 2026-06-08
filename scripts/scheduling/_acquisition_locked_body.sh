#!/usr/bin/env bash
# Runs under with_file_lock.py — do not invoke directly.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
PYTHON="${AI_JOB_AGENT_PYTHON:-$ROOT/venv/bin/python}"

echo ""
echo "--- python main.py ($(date -Iseconds)) ---"
"$PYTHON" main.py
MAIN_EXIT=$?

echo ""
echo "--- validate_sqlite_parity --mode production --fail-on-error ($(date -Iseconds)) ---"
set +e
"$PYTHON" scripts/validate_sqlite_parity.py --mode production --fail-on-error
PARITY_EXIT=$?
set -e

echo ""
echo "============================================================"
echo "Scheduled acquisition finished: $(date -Iseconds)"
echo "main.py exit=$MAIN_EXIT parity exit=$PARITY_EXIT"
echo "============================================================"

if [[ "$MAIN_EXIT" -ne 0 ]]; then
  exit "$MAIN_EXIT"
fi
exit "$PARITY_EXIT"
