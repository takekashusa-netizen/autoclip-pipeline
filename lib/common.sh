#!/usr/bin/env bash
# lib/common.sh — sourced by run_pipeline.sh and every skills/*/run.sh.
# Central place for path resolution + job-state access so skills never
# duplicate this logic or touch job.json directly.

# Resolve repo root regardless of where this is sourced from.
COMMON_SH_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PIPELINE_ROOT="$(cd "${COMMON_SH_DIR}/.." && pwd)"
export JOBSTATE="python3 ${PIPELINE_ROOT}/lib/jobstate.py"

log() { echo "  [$(date +%H:%M:%S)] $*"; }
export -f log

job_dir()      { echo "${PIPELINE_ROOT}/projects/$1"; }
job_raw_dir()  { echo "${PIPELINE_ROOT}/projects/$1/raw"; }
job_work_dir() { echo "${PIPELINE_ROOT}/projects/$1/work"; }
job_render_dir() { echo "${PIPELINE_ROOT}/projects/$1/render"; }
export -f job_dir job_raw_dir job_work_dir job_render_dir

# Find the raw source file for a job (first file in projects/<job>/raw/).
job_raw_file() {
  local job="$1"
  find "$(job_raw_dir "$job")" -maxdepth 1 -type f ! -name '.gitkeep' 2>/dev/null | head -n1 || true
}
export -f job_raw_file

state_init()      { $JOBSTATE init "$1" "$2" "$3"; }
state_get()       { $JOBSTATE get "$1" "$2" "${@:3}"; }
state_set()       { $JOBSTATE set "$1" "$2" "$3"; }
state_step_done() { $JOBSTATE step-done "$1" "$2"; }
state_mark()      { $JOBSTATE mark "$1" "$2" "$3" "${4:-}"; }

# Aborts if free space on the pipeline volume is less than N x raw file size.
# Default margin=4 covers rough-cut render + graphics render + captions
# render + scored render existing briefly before prune runs.
check_disk_space() {
  local job="$1" margin="${2:-4}"
  local raw
  raw="$(job_raw_file "$job")"
  [[ -z "$raw" ]] && return 0

  local raw_bytes avail_bytes required_bytes
  raw_bytes=$(stat -c%s "$raw" 2>/dev/null || stat -f%z "$raw")
  avail_bytes=$(df -P "${PIPELINE_ROOT}" | awk 'NR==2{print $4*1024}')
  required_bytes=$(( raw_bytes * margin ))

  if (( avail_bytes < required_bytes )); then
    echo "abort: insufficient disk space for job '${job}'" >&2
    echo "  need ~$(( required_bytes / 1024 / 1024 )) MB, have $(( avail_bytes / 1024 / 1024 )) MB free" >&2
    return 1
  fi
}
export -f check_disk_space

# Load a format config value, e.g. format_get short-tiktok-raw captions.preset
format_get() {
  local format="$1" path="$2"
  python3 - "$PIPELINE_ROOT/formats/${format}.json" "$path" <<'PY'
import json, sys
data = json.load(open(sys.argv[1]))
cur = data
for part in sys.argv[2].split("."):
    if isinstance(cur, dict):
        cur = cur.get(part)
    elif isinstance(cur, list) and part.isdigit():
        i = int(part)
        cur = cur[i] if i < len(cur) else None
    else:
        cur = None
print(cur if cur is not None else "")
PY
}
