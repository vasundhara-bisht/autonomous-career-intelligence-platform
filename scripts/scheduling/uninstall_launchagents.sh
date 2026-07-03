#!/usr/bin/env bash
# Uninstall ai-job-agent LaunchAgents (Task 3 rollback support).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
LAUNCHD_DIR="${HOME}/Library/LaunchAgents"
UID_NUM="$(id -u)"
DOMAIN="gui/${UID_NUM}"

UNINSTALL_ACQUISITION=1
UNINSTALL_LIFECYCLE=1
UNINSTALL_BACKUP=1

usage() {
  cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Boot out and remove installed LaunchAgent plists.

Options:
  --acquisition-only   Remove acquisition agent only
  --lifecycle-only     Remove lifecycle monitor agent only
  --keep-backup        Do not remove backup agent (if installed)
  -h, --help           Show this help

Also removes stale lock files under /tmp when removing the matching agent.
See docs/LIFECYCLE_MONITOR_TASK3_ACTIVATION.md §Rollback.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --acquisition-only)
      UNINSTALL_ACQUISITION=1
      UNINSTALL_LIFECYCLE=0
      UNINSTALL_BACKUP=0
      shift
      ;;
    --lifecycle-only)
      UNINSTALL_ACQUISITION=0
      UNINSTALL_LIFECYCLE=1
      UNINSTALL_BACKUP=0
      shift
      ;;
    --keep-backup)
      UNINSTALL_BACKUP=0
      shift
      ;;
    -h | --help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

uninstall_one() {
  local label="$1"
  local dest="${LAUNCHD_DIR}/${label}.plist"

  if launchctl print "${DOMAIN}/${label}" &>/dev/null; then
    launchctl bootout "$DOMAIN" "$dest" 2>/dev/null || true
    echo "Booted out ${DOMAIN}/${label}"
  else
    echo "Agent not loaded: ${label}"
  fi

  if [[ -f "$dest" ]]; then
    rm -f "$dest"
    echo "Removed $dest"
  fi
}

if [[ "$UNINSTALL_ACQUISITION" -eq 1 ]]; then
  uninstall_one "com.vasundhara-bisht.ai-job-agent.acquisition"
  rm -f /tmp/ai-job-agent-acquisition.lock
fi

if [[ "$UNINSTALL_LIFECYCLE" -eq 1 ]]; then
  uninstall_one "com.vasundhara-bisht.ai-job-agent.lifecycle-monitor"
  rm -f /tmp/ai-job-agent-lifecycle-monitor.lock
fi

if [[ "$UNINSTALL_BACKUP" -eq 1 ]]; then
  uninstall_one "com.vasundhara-bisht.ai-job-agent.backup"
  rm -f /tmp/ai-job-agent-backup.lock
fi

echo ""
echo "Manual acquisition still works: python main.py"
echo "Manual lifecycle monitor: python scripts/run_lifecycle_monitor.py --apply"
echo ""
echo "Post–Task 4: listing-status visibility is always on; monitor rollback = lifecycle plist unload only."
echo "See docs/LIFECYCLE_MONITOR_TASK3_ACTIVATION.md"
