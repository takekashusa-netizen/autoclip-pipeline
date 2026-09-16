#!/usr/bin/env bash
set -uo pipefail

# restart_poller.sh
#
# Now launchd-managed (com.takekash.poller) — real env vars live in
# the plist itself now, not your shell's exports, so this no longer
# needs QUEUE_URL/QUEUE_SECRET set before running it.

PLIST="$HOME/Library/LaunchAgents/com.takekash.poller.plist"
LABEL="com.takekash.poller"

if [[ ! -f "$PLIST" ]]; then
  echo "restart_poller: $PLIST not found — launchd service isn't installed" >&2
  exit 1
fi

echo "== restart_poller: restarting via launchd =="
launchctl kickstart -k "gui/$(id -u)/${LABEL}" 2>/dev/null || {
  echo "restart_poller: kickstart failed, trying unload/load instead" >&2
  launchctl unload "$PLIST" 2>/dev/null
  launchctl load "$PLIST"
}

sleep 2
if launchctl list | grep -q "$LABEL"; then
  echo "== restart_poller: CONFIRMED — registered with launchd, logging to poller.log =="
  echo "== check status any time: tail -f poller.log =="
else
  echo "restart_poller: not showing in launchctl list — check poller.log for a real error" >&2
  exit 1
fi
