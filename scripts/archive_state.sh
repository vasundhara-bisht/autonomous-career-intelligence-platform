#!/usr/bin/env bash
# Archive runtime persistence before clean-state reset. Non-destructive.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

COMPRESS=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --compress) COMPRESS=1; shift ;;
    -h|--help)
      echo "Usage: $0 [--compress]"
      echo "Creates archive/reset-YYYYMMDD-HHMM/ with MANIFEST.json"
      exit 0
      ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done

RESET_ID="reset-$(date +%Y%m%d-%H%M)"
ARCHIVE_DIR="$ROOT/archive/$RESET_ID"
mkdir -p "$ARCHIVE_DIR"

copy_if_exists() {
  local src="$1"
  local dest_name="${2:-$(basename "$src")}"
  if [[ -f "$src" ]]; then
    cp "$src" "$ARCHIVE_DIR/$dest_name"
    echo "  archived: $src -> $dest_name"
  else
    echo "  skip (missing): $src"
  fi
}

echo "Archiving to $ARCHIVE_DIR"
copy_if_exists "data/historical_jobs.csv"
copy_if_exists "data/jobs.csv"
copy_if_exists "data/job_descriptions.csv"
copy_if_exists "data/recruiter_crm.csv"
copy_if_exists "data/job_state.csv"
copy_if_exists "data/.linkedin_query_state.json" "linkedin_query_state.json"
copy_if_exists "data/linkedin_auth.json"
copy_if_exists "data/instahyre_auth.json"

python3 "$ROOT/scripts/archive_state.py" "$ARCHIVE_DIR"

if [[ "$COMPRESS" -eq 1 ]]; then
  TARBALL="$ROOT/archive/${RESET_ID}.tar.gz"
  tar -czf "$TARBALL" -C "$ROOT/archive" "$RESET_ID"
  echo "Compressed: $TARBALL"
fi

echo ""
echo "Archive complete: $ARCHIVE_DIR"
echo "RESET_ID=$RESET_ID"
echo "Use with: ./scripts/reset_state.sh --archive-id $RESET_ID"
