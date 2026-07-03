#!/usr/bin/env bash
# Canonical Streamlit dashboard launcher — loads repo-root .env before Streamlit.
# Use ./scripts/run_dashboard.sh (loads repo-root .env before Streamlit).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

STREAMLIT="${AI_JOB_AGENT_STREAMLIT:-$ROOT/venv/bin/streamlit}"
if [[ ! -x "$STREAMLIT" ]]; then
  if command -v streamlit >/dev/null 2>&1; then
    STREAMLIT="$(command -v streamlit)"
  else
    echo "ERROR: streamlit not found at $ROOT/venv/bin/streamlit"
    echo "Create venv: python3 -m venv venv && pip install -r requirements.txt"
    exit 1
  fi
fi

if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
  echo "Loaded environment from $ROOT/.env"
else
  echo "Note: $ROOT/.env not found — using process defaults for dashboard flags"
fi

exec "$STREAMLIT" run dashboard/app.py "$@"
