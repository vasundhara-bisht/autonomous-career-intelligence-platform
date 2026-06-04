#!/usr/bin/env bash
# Profile-driven runtime reset wrapper. DESTRUCTIVE unless --dry-run.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

ARCHIVE_ID=""
PROFILE=""

usage() {
  echo "Usage: $0 --archive-id reset-YYYYMMDD-HHMM --profile <bootstrap|acquisition|crm-preserving|full> [options]"
  echo ""
  echo "Profiles:"
  echo "  bootstrap       Reset job memory, descriptions, query state, job state, and recruiter CRM; preserve auth"
  echo "  acquisition     Reset jobs.csv and LinkedIn query state only"
  echo "  crm-preserving  Reset job memory/descriptions/query state; preserve recruiter CRM and auth"
  echo "  full            Reset all runtime state except auth by default"
  echo ""
  echo "Options:"
  echo "  --dry-run                 Print reset plan only"
  echo "  --no-confirm              Skip interactive confirmation"
  echo "  --use-template-fallback   Use scripts/templates/*.header.csv schemas"
  echo "  --reset-auth              Also reset LinkedIn/Instahyre auth storage states"
  echo "  --confirm-reset-auth      Required with --reset-auth --no-confirm"
  exit "${1:-0}"
}

ARGS=("$@")
while [[ $# -gt 0 ]]; do
  case "$1" in
    --archive-id) ARCHIVE_ID="$2"; shift 2 ;;
    --profile) PROFILE="$2"; shift 2 ;;
    --dry-run|--no-confirm|--use-template-fallback|--reset-auth|--confirm-reset-auth) shift ;;
    -h|--help) usage 0 ;;
    *) echo "Unknown option: $1" >&2; usage 2 ;;
  esac
done

if [[ -z "$ARCHIVE_ID" ]]; then
  echo "ERROR: --archive-id is required (proves archive_state.sh was run)." >&2
  usage 2
fi

if [[ -z "$PROFILE" ]]; then
  echo "ERROR: --profile is required." >&2
  usage 2
fi

MANIFEST="$ROOT/archive/$ARCHIVE_ID/MANIFEST.json"
if [[ ! -f "$MANIFEST" ]]; then
  echo "ERROR: Missing archive manifest: $MANIFEST" >&2
  echo "Run ./scripts/archive_state.sh first." >&2
  exit 1
fi

if pgrep -f "python.*main.py" >/dev/null 2>&1 || pgrep -f "streamlit.*app.py" >/dev/null 2>&1; then
  echo "WARNING: main.py or Streamlit may be running. Stop before reset." >&2
fi

python3 "$ROOT/scripts/reset_runtime.py" "${ARGS[@]}"
