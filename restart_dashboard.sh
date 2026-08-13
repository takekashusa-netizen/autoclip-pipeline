#!/usr/bin/env bash
set -uo pipefail

# restart_dashboard.sh [--port 8765]
#
# The permanent fix for "I edited dashboard.py but the running server
# still has the old code" — Python doesn't hot-reload, so every code
# change needs a real restart. This used to mean manually hunting down
# PIDs for both dashboard.py AND its caffeinate wrapper, killing them
# separately, then relaunching by hand — a multi-step process that's
# gone wrong more than once tonight. This does it all in one real,
# verified command: kill anything currently running by name (not by a
# PID you have to look up first), wait for it to actually be gone,
# relaunch with the same caffeinate + venv-python pattern used
# everywhere else, then confirm with a real HTTP health check before
# declaring success — not just "the process started," but "it's
# actually answering requests."

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
port=8765
if [[ "${1:-}" == "--port" ]]; then
  port="$2"
fi

echo "== restart_dashboard: stopping any existing dashboard.py/caffeinate =="
pkill -f "dashboard.py --port ${port}" 2>/dev/null
pkill -f "caffeinate -dis python3 ${ROOT}/dashboard.py" 2>/dev/null
pkill -f "caffeinate -dis python3 dashboard.py" 2>/dev/null
sleep 1

# confirm it's actually gone before relaunching — a real check, not an assumption
if pgrep -f "dashboard.py --port ${port}" > /dev/null 2>&1; then
  echo "restart_dashboard: a dashboard.py process survived the kill — forcing it" >&2
  pkill -9 -f "dashboard.py --port ${port}" 2>/dev/null
  sleep 1
fi

echo "== restart_dashboard: launching fresh (with caffeinate sleep protection) =="
cd "$ROOT"
nohup caffeinate -dis python3 dashboard.py --port "$port" > dashboard.log 2>&1 &
new_pid=$!
sleep 2

echo "== restart_dashboard: verifying it's actually responding (not just started) =="
if curl -sf "http://localhost:${port}/api/jobs" > /dev/null 2>&1; then
  echo "== restart_dashboard: CONFIRMED — genuinely up and responding at http://localhost:${port} =="
else
  echo "restart_dashboard: launched (PID ${new_pid}) but not yet responding — check dashboard.log for a real error" >&2
  exit 1
fi
