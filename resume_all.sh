#!/usr/bin/env bash
set -euo pipefail

# Usage: ./resume_all.sh [--dry-run] [--parallel N]
#
# Scans projects/ for any job that isn't finished (export step != done)
# and isn't currently mid-run (no .lock file), and re-runs its pipeline.
# Safe to run any time — every step is already skip-if-done via job.json,
# so this never redoes finished work, it only picks up where a job left
# off after a crashed terminal, closed window, or interrupted session.
#
# --parallel N runs up to N jobs concurrently instead of one at a time.
# Each still runs via the normal run_pipeline.sh, fully detached (own
# process group, output to logs/<job>.log) — safe from terminal
# interrupts the same way a single nohup'd run is. Default is 1
# (sequential, original behavior).
#
# Real expectation-setting: whisper transcription is CPU-bound. Running
# N transcriptions in parallel on a machine with fewer than N idle cores
# doesn't multiply throughput — it splits the same CPU across more work.
# The actual win is on I/O/network-bound stretches (downloads, model
# loading) and when jobs are in different stages at different times, not
# a guaranteed Nx speedup on pure transcription time.
#
# Single-output jobs resume via run_pipeline.sh. Clip-pipeline sub-jobs
# (job__clipNN) also resume via run_pipeline.sh directly — by the time a
# sub-job exists, the parent's transcription/clip-selection work is
# already done, so each sub-job is independently resumable on its own.

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${ROOT}/lib/common.sh"

dry_run=false
parallel=1
args=("$@")
i=0
while [[ $i -lt ${#args[@]} ]]; do
  case "${args[$i]}" in
    --dry-run) dry_run=true ;;
    --parallel) i=$((i+1)); parallel="${args[$i]}" ;;
  esac
  i=$((i+1))
done

if [[ ! -d "${ROOT}/projects" ]]; then
  echo "no projects/ directory — nothing to resume"
  exit 0
fi

mkdir -p "${ROOT}/logs"

found=0
resumed=0
skipped_locked=0
skipped_done=0
skipped_no_raw=0
declare -a bg_pids=()

# Portable concurrency throttle (no `wait -n`, which needs bash 5+ and
# macOS ships bash 3.2 by default) — poll active background PIDs and
# prune finished ones until we're under the cap.
wait_for_slot() {
  while [[ ${#bg_pids[@]} -ge $parallel ]]; do
    local still_running=()
    for pid in "${bg_pids[@]}"; do
      if kill -0 "$pid" 2>/dev/null; then
        still_running+=("$pid")
      fi
    done
    bg_pids=("${still_running[@]}")
    [[ ${#bg_pids[@]} -ge $parallel ]] && sleep 2
  done
}

for job_dir in "${ROOT}"/projects/*/; do
  job="$(basename "$job_dir")"
  job_json="${job_dir}job.json"
  [[ -f "$job_json" ]] || continue
  found=$((found + 1))

  if [[ -f "${job_dir}.lock" ]]; then
    echo "skip ${job}: locked (already running, or a stale lock — check manually if this persists)"
    skipped_locked=$((skipped_locked + 1))
    continue
  fi

  export_status="$(python3 -c "
import json
try:
    d = json.load(open('${job_json}'))
    print(d.get('steps', {}).get('export', {}).get('status', 'pending'))
except Exception:
    print('error')
")"

  if [[ "$export_status" == "done" ]]; then
    skipped_done=$((skipped_done + 1))
    continue
  fi

  diagnosis_category="$(python3 -c "
import json
try:
    d = json.load(open('${job_json}'))
    diag = d.get('diagnosis') or {}
    print(diag.get('category', ''))
except Exception:
    print('')
")"

  if [[ -n "$diagnosis_category" ]]; then
    diagnosis_reason="$(python3 -c "
import json
d = json.load(open('${job_json}'))
print((d.get('diagnosis') or {}).get('reason', ''))
")"
    echo "note: ${job}'s last attempt failed — ${diagnosis_reason}"

    if [[ "$diagnosis_category" == "missing_dependency" ]]; then
      if ! python3 -c "import faster_whisper" 2>/dev/null; then
        echo "skip ${job}: still missing faster_whisper — install it before resuming this job (pip install faster-whisper)"
        continue
      fi
      echo "  faster_whisper now importable — retrying"
    fi
  fi

  format="$(python3 -c "
import json
print(json.load(open('${job_json}')).get('format', ''))
")"
  if [[ -z "$format" ]]; then
    echo "skip ${job}: no format recorded in job.json, can't resume automatically"
    continue
  fi

  raw_file="$(job_raw_file "$job")"
  if [[ -z "$raw_file" ]]; then
    echo "skip ${job}: no raw file present (download never completed) — re-submit this one manually"
    skipped_no_raw=$((skipped_no_raw + 1))
    continue
  fi

  echo "== resuming ${job} (format=${format}) =="
  if [[ "$dry_run" == true ]]; then
    echo "  (dry run — would run: ./run_pipeline.sh ${job} ${format})"
    continue
  fi

  if [[ "$parallel" -le 1 ]]; then
    "${ROOT}/run_pipeline.sh" "$job" "$format" || \
      log "  ${job}: stopped (paused for review, or hit an error — check job.json)"
    resumed=$((resumed + 1))
  else
    wait_for_slot
    log "  launching ${job} in background -> logs/${job}.log"
    nohup "${ROOT}/run_pipeline.sh" "$job" "$format" > "${ROOT}/logs/${job}.log" 2>&1 &
    bg_pids+=("$!")
    # NOT disowned deliberately — this script's own `wait "$pid"` loop
    # below needs to actually track these to block correctly. disown
    # removes bash's job tracking, which makes `wait` on that PID a
    # no-op instead of really blocking, so the script would print its
    # summary before the jobs actually finished. nohup alone (kept
    # above) already protects each job from SIGHUP if the terminal
    # running resume_all.sh itself closes — that's the actual
    # protection needed, not disown.
    resumed=$((resumed + 1))
  fi
done

if [[ "$parallel" -gt 1 && "$dry_run" == false ]]; then
  echo "waiting for remaining background jobs to finish (check logs/<job>.log for live progress, or use track.py)..."
  for pid in "${bg_pids[@]}"; do
    wait "$pid" 2>/dev/null || true
  done
fi

echo
echo "== resume_all summary: ${found} jobs found, ${resumed} resumed, ${skipped_done} already done, ${skipped_locked} locked/running, ${skipped_no_raw} missing raw file =="
