#!/usr/bin/env bash
# Install or reload user LaunchAgents for ai-job-agent scheduling.
# Does not enable secrets; ensure .env exists with OPENAI_API_KEY before loading.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
LAUNCHD_DIR="${HOME}/Library/LaunchAgents"
UID_NUM="$(id -u)"
DOMAIN="gui/${UID_NUM}"

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
chmod +x "${ROOT}/scripts/scheduling/_acquisition_locked_body.sh"
chmod +x "${ROOT}/scripts/scheduling/_backup_locked_body.sh"
chmod +x "${ROOT}/scripts/scheduling/with_file_lock.py"

install_one \
  "${ROOT}/scripts/scheduling/launchd/com.vasundhara-bisht.ai-job-agent.acquisition.plist.template" \
  "com.vasundhara-bisht.ai-job-agent.acquisition"

echo ""
echo "Acquisition agent: 07:00 and 19:00 local time."
echo "Manual test: launchctl kickstart -k ${DOMAIN}/com.vasundhara-bisht.ai-job-agent.acquisition"
echo ""

if [[ "${1:-}" == "--with-backup" ]]; then
  install_one \
    "${ROOT}/scripts/scheduling/launchd/com.vasundhara-bisht.ai-job-agent.backup.plist.template" \
    "com.vasundhara-bisht.ai-job-agent.backup"
  echo "Backup agent: Sunday 23:00 local time."
else
  echo "Skipped backup agent (pass --with-backup to install)."
fi

echo "Done. See docs/SCHEDULER_SETUP.md"
