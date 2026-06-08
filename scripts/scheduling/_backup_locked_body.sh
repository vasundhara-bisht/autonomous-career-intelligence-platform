#!/usr/bin/env bash
# Runs under with_file_lock.py — do not invoke directly.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
PYTHON="${AI_JOB_AGENT_PYTHON:-$ROOT/venv/bin/python}"

echo ""
echo "--- archive_state.sh ($(date -Iseconds)) ---"
./scripts/archive_state.sh

echo ""
echo "--- export_csv_memory.py --all ($(date -Iseconds)) ---"
"$PYTHON" scripts/export_csv_memory.py --all

echo ""
echo "--- validate_sqlite_parity --mode source-of-truth --fail-on-error ($(date -Iseconds)) ---"
"$PYTHON" scripts/validate_sqlite_parity.py --mode source-of-truth --fail-on-error

echo ""
echo "============================================================"
echo "Scheduled backup finished: $(date -Iseconds)"
echo "============================================================"
