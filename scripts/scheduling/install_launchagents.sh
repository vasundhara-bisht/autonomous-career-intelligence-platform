#!/usr/bin/env bash
# Install or reload user LaunchAgents for ai-job-agent scheduling (Task 3).
# Does not enable secrets; ensure .env exists with OPENAI_API_KEY before loading.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
LAUNCHD_DIR="${HOME}/Library/LaunchAgents"
UID_NUM="$(id -u)"
DOMAIN="gui/${UID_NUM}"

INSTALL_ACQUISITION=1
INSTALL_LIFECYCLE=1
INSTALL_BACKUP=0

usage() {
  cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Install or reload LaunchAgents from repo templates.

Options:
  --with-backup        Also install weekly backup agent (Sunday 23:00 local)
  --acquisition-only   Install/reload acquisition agent only
  --lifecycle-only     Install/reload lifecycle monitor agent only
  -h, --help           Show this help

Default: acquisition (09:00 / 21:00 IST) + lifecycle monitor (17:00 IST once daily; OHM Phase 1 template).
See docs/SCHEDULER_SETUP.md and docs/LIFECYCLE_MONITOR_TASK3_ACTIVATION.md.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --with-backup)
      INSTALL_BACKUP=1
      shift
      ;;
    --acquisition-only)
      INSTALL_ACQUISITION=1
      INSTALL_LIFECYCLE=0
      shift
      ;;
    --lifecycle-only)
      INSTALL_ACQUISITION=0
      INSTALL_LIFECYCLE=1
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

install_one() {
  local template="$1"
  local label="$2"
  local dest="${LAUNCHD_DIR}/${label}.plist"

  sed "s|@REPO_ROOT@|${ROOT}|g" "$template" >"$dest"
  echo "Wrote $dest"

  if launchctl print "${DOMAIN}/${label}" &>/dev/null; then
    launchctl bootout "$DOMAIN" "$dest" 2>/dev/null || true
  fi
  launchctl bootstrap "$DOMAIN" "$dest"
  echo "Loaded ${DOMAIN}/${label}"
}

mkdir -p "${ROOT}/logs/scheduled"
chmod +x "${ROOT}/scripts/scheduling/run_scheduled_acquisition.sh"
chmod +x "${ROOT}/scripts/scheduling/run_scheduled_backup.sh"
chmod +x "${ROOT}/scripts/scheduling/run_scheduled_lifecycle_monitor.sh"
chmod +x "${ROOT}/scripts/scheduling/_acquisition_locked_body.sh"
chmod +x "${ROOT}/scripts/scheduling/_backup_locked_body.sh"
chmod +x "${ROOT}/scripts/scheduling/_lifecycle_monitor_locked_body.sh"
chmod +x "${ROOT}/scripts/scheduling/with_file_lock.py"
chmod +x "${ROOT}/scripts/scheduling/probe_file_lock.py"

if [[ "$INSTALL_ACQUISITION" -eq 1 ]]; then
  install_one \
    "${ROOT}/scripts/scheduling/launchd/com.vasundhara-bisht.ai-job-agent.acquisition.plist.template" \
    "com.vasundhara-bisht.ai-job-agent.acquisition"
  echo ""
  echo "Acquisition agent: 09:00 and 21:00 IST."
  echo "Manual test: launchctl kickstart -k ${DOMAIN}/com.vasundhara-bisht.ai-job-agent.acquisition"
  echo ""
fi

if [[ "$INSTALL_LIFECYCLE" -eq 1 ]]; then
  install_one \
    "${ROOT}/scripts/scheduling/launchd/com.vasundhara-bisht.ai-job-agent.lifecycle-monitor.plist.template" \
    "com.vasundhara-bisht.ai-job-agent.lifecycle-monitor"
  echo ""
  echo "Lifecycle monitor agent: 17:00 IST once daily (OHM Phase 1 template)."
  echo "Manual test: launchctl kickstart -k ${DOMAIN}/com.vasundhara-bisht.ai-job-agent.lifecycle-monitor"
  echo ""
fi

if [[ "$INSTALL_BACKUP" -eq 1 ]]; then
  install_one \
    "${ROOT}/scripts/scheduling/launchd/com.vasundhara-bisht.ai-job-agent.backup.plist.template" \
    "com.vasundhara-bisht.ai-job-agent.backup"
  echo "Backup agent: Sunday 23:00 local time."
else
  echo "Skipped backup agent (pass --with-backup to install)."
fi

echo ""
echo "Dashboard: use ./scripts/run_dashboard.sh (listing_status visibility is always on after Task 4)."
echo "  then start dashboard: ./scripts/run_dashboard.sh"
echo ""
echo "Done. See docs/SCHEDULER_SETUP.md and docs/LIFECYCLE_MONITOR_TASK3_ACTIVATION.md"
