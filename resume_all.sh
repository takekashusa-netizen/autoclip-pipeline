#!/usr/bin/env bash
set -euo pipefail

# Usage: ./resume_all.sh [--dry-run]
#
# Scans projects/ for any job that isn't finished (export step != done)
# and isn't currently mid-run (no .lock file), and re-runs its pipeline.
# Safe to run any time — every step is already skip-if-done via job.json,
# so this never redoes finished work, it only picks up where a job left
# off after a crashed terminal, closed window, or interrupted session.
#
# Single-output jobs resume via run_pipeline.sh. Clip-pipeline sub-jobs
# (job__clipNN) also resume via run_pipeline.sh directly — by the time a
# sub-job exists, the parent's transcription/clip-selection work is
# already done, so each sub-job is independently resumable on its own.

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${ROOT}/lib/common.sh"

dry_run=false
[[ "${1:-}" == "--dry-run" ]] && dry_run=true

if [[ ! -d "${ROOT}/projects" ]]; then
  echo "no projects/ directory — nothing to resume"
  exit 0
fi

found=0
resumed=0
skipped_locked=0
skipped_done=0
skipped_no_raw=0

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
  else
    "${ROOT}/run_pipeline.sh" "$job" "$format" || \
      log "  ${job}: stopped (paused for review, or hit an error — check job.json)"
    resumed=$((resumed + 1))
  fi
done

echo
echo "== resume_all summary: ${found} jobs found, ${resumed} resumed, ${skipped_done} already done, ${skipped_locked} locked/running, ${skipped_no_raw} missing raw file =="
