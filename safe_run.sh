#!/usr/bin/env bash
set -uo pipefail
# safe_run.sh <script> [args...]
#
# The permanent fix for two real problems that cost real time tonight:
#   1. An accidental Ctrl+C in the wrong terminal killing a real job
#      mid-render (exit 130 — this happened, not a mystery bug).
#   2. macOS sleep/display-sleep silently suspending a long-running job
#      with zero error trace (confirmed via caffeinate -dis fixing it).
#
# This wraps ANY pipeline command (run_pipeline.sh, clip_pipeline.sh,
# resume_all.sh, watch_channel.sh, ...) so it ALWAYS runs:
#   - fully detached (nohup) — closing the terminal, or Ctrl+C'ing this
#     wrapper itself, does NOT touch the actual job underneath
#   - with full sleep prevention (caffeinate -dis) for the job's entire
#     runtime, not just while a specific step happens to be watched
#   - logged to a predictable, timestamped file you can tail anytime
#
# Usage — same as running the command directly, just prefixed:
#   ./safe_run.sh ./run_pipeline.sh 881bb850f75b__montage01 long-form-youtube
#   ./safe_run.sh ./clip_pipeline.sh 881bb850f75b long-form-youtube --montage-minutes 15 --montage-count 2
#   ./safe_run.sh ./resume_all.sh --parallel 2
#
# Prints the PID and log path immediately, then returns your terminal —
# safe to close the window, Ctrl+C anything else in that terminal, let
# the Mac's screen lock, whatever. Check progress anytime with:
#   tail -f <printed log path>
# Check if it's done:
#   ps -p <printed PID>   (no output = finished)

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
mkdir -p "${ROOT}/logs/safe_run"

if [[ $# -lt 1 ]]; then
  echo "usage: ./safe_run.sh <script> [args...]" >&2
  exit 1
fi

script_name="$(basename "$1" | sed 's/\.[^.]*$//')"
timestamp="$(date +%Y%m%d_%H%M%S)"
log_file="${ROOT}/logs/safe_run/${script_name}_${timestamp}.log"

# Automated preflight check before every launch — the direct fix for
# tonight's pattern of launching a job only to have it die 20 seconds in
# from something checkable in advance (a dead import, a stale lock).
# Real runtime verification, not assumptions; auto-fixes what's safely
# fixable (stale locks) and refuses to launch with a clear reason for
# anything it can't. job_id is best-effort extracted from the first
# script argument that looks like one (not a flag, not a path) — if we
# can't tell, the lock check is simply skipped, everything else still runs.
job_id_guess=""
for arg in "${@:2}"; do
  [[ "$arg" == --* ]] && continue
  job_id_guess="$arg"
  break
done
if ! python3 "${ROOT}/preflight.py" "$job_id_guess"; then
  echo "safe_run.sh: preflight check failed — refusing to launch. Fix the problem(s) above and retry." >&2
  exit 1
fi

# graceful degradation if caffeinate isn't available (macOS-only) — still
# get the interrupt/terminal-close protection from nohup+disown either
# way, just without sleep-prevention on non-macOS systems
if command -v caffeinate >/dev/null 2>&1; then
  nohup caffeinate -dis "$@" > "$log_file" 2>&1 &
else
  echo "note: caffeinate not available on this system — running without sleep-prevention (still fully detached/interrupt-proof)" >&2
  nohup "$@" > "$log_file" 2>&1 &
fi
pid=$!
disown  # deliberately WITHOUT tracking for `wait` here (unlike resume_all.sh's
        # internal parallel mode) — this wrapper's whole purpose is to hand the
        # job off and return your terminal immediately, not block on it

echo "== launched detached, sleep-protected: PID ${pid} =="
echo "== log: ${log_file} =="
echo "== check progress:  tail -f ${log_file} =="
echo "== check if done:   ps -p ${pid}   (no output = finished) =="
echo "== this terminal is free — closing it, Ctrl+C'ing anything else here, or your Mac sleeping will NOT affect this job =="
