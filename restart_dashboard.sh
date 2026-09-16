#!/usr/bin/env bash
set -uo pipefail

# restart_dashboard.sh
#
# Now launchd-managed (com.takekash.dashboard) instead of a manual
# nohup process — this just tells launchd to restart it cleanly via
# `kickstart -k`, then does the same real, retrying health check as
# before rather than a single fragile check.

PLIST="$HOME/Library/LaunchAgents/com.takekash.dashboard.plist"
LABEL="com.takekash.dashboard"
port=8765

if [[ ! -f "$PLIST" ]]; then
  echo "restart_dashboard: $PLIST not found — launchd service isn't installed" >&2
  exit 1
fi

echo "== restart_dashboard: restarting via launchd =="
launchctl kickstart -k "gui/$(id -u)/${LABEL}" 2>/dev/null || {
  echo "restart_dashboard: kickstart failed, trying unload/load instead" >&2
  launchctl unload "$PLIST" 2>/dev/null
  launchctl load "$PLIST"
}

echo "== restart_dashboard: verifying it's actually responding (not just started) =="
max_attempts=20
attempt=0
up=false
while [[ $attempt -lt $max_attempts ]]; do
  if curl -sf "http://localhost:${port}/api/jobs" > /dev/null 2>&1; then
    up=true
    break
  fi
  sleep 1
  attempt=$((attempt + 1))
done

if [[ "$up" == "true" ]]; then
  echo "== restart_dashboard: CONFIRMED — genuinely up and responding at http://localhost:${port} (after ${attempt}s) =="
else
  echo "restart_dashboard: still not responding after ${max_attempts}s — check dashboard.log for a real error" >&2
  exit 1
fi
