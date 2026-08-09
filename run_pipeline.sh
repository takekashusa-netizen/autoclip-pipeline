#!/usr/bin/env bash
set -euo pipefail

# Usage: ./run_pipeline.sh <job> <format> [--skip-music] [--to-premiere] [--force] [--content-type podcast|gaming|irl] [--auto-approve]
#   job     job id, used for projects/<job>/... and outputs/<job>.final.mp4
#   format  one of: short-explainer | short-tiktok-raw | long-form-youtube
#   --force  re-run steps even if job.json says they're already done
#   --content-type  overrides the format's default reframe strategy —
#                   'gaming' forces letterbox (no crop) so HUD/killfeed
#                   survives; defaults to the format's own content_type
#   --auto-approve  skips the manual second-pass review pause entirely —
#                   the pipeline runs straight through to export with no
#                   human check in between. This removes the one built-in
#                   quality gate; use it deliberately, not as a default.

job="${1:?job id required}"
format="${2:?format required (short-explainer|short-tiktok-raw|long-form-youtube)}"
shift 2

skip_music=false
to_premiere=false
force=false
content_type=""
auto_approve=false
args=("$@")
i=0
while [[ $i -lt ${#args[@]} ]]; do
  case "${args[$i]}" in
    --skip-music) skip_music=true ;;
    --to-premiere) to_premiere=true ;;
    --force) force=true ;;
    --content-type) i=$((i+1)); content_type="${args[$i]}" ;;
    --auto-approve) auto_approve=true ;;
  esac
  i=$((i+1))
done
export CONTENT_TYPE="$content_type"

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/common.sh"

format_config="${PIPELINE_ROOT}/formats/${format}.json"
if [[ ! -f "$format_config" ]]; then
  echo "unknown format: $format (expected a file at $format_config)" >&2
  exit 1
fi

# run <step-name> <skill-cmd...>  — skips if job.json already marks it done,
# unless --force. This is what lets a job resume after the manual
# second-pass review, or after a crash, without redoing finished work.
run_step() {
  local step="$1"; shift
  if [[ "$force" == false ]] && state_step_done "$job" "$step" >/dev/null 2>&1; then
    log "[$step] already done, skipping (use --force to redo)"
    return 0
  fi
  "$@"
  state_mark "$job" "$step" "done"
}

echo "== pipeline: job=${job} format=${format} =="
mkdir -p "$(job_raw_dir "$job")"

check_disk_space "$job" || exit 1

if [[ ! -f "$(job_dir "$job")/job.json" ]]; then
  raw_file="$(job_raw_file "$job")"
  state_init "$job" "$format" "${raw_file:-}"
fi

# Real bug found and fixed: run_pipeline.sh had NO locking of its own —
# only the web app's background-task wrapper created .lock files. Running
# resume_all.sh (or run_pipeline.sh directly) more than once while a job
# was still mid-run spawned duplicate ffmpeg processes racing to write the
# SAME output file simultaneously. This is the actual fix, at the actual
# entry point every execution path goes through.
lock_file="$(job_dir "$job")/.lock"
if [[ -f "$lock_file" ]]; then
  existing_pid="$(cat "$lock_file" 2>/dev/null || echo "")"
  if [[ -n "$existing_pid" ]] && kill -0 "$existing_pid" 2>/dev/null; then
    echo "abort: job '${job}' is already running (pid ${existing_pid}) — refusing to start a duplicate run" >&2
    exit 1
  fi
  echo "note: found a stale lock (pid ${existing_pid} is not running) — proceeding" >&2
fi
mkdir -p "$(job_dir "$job")"
echo $$ > "$lock_file"

# Clear any stale error/diagnosis from a previous failed attempt — without
# this, a job that failed hours ago keeps showing as FAILED forever even
# after it starts succeeding, since only the web app was clearing this
# field. run_pipeline.sh is the actual common entry point for every
# execution path (web app, CLI, resume_all.sh), so this belongs here.
state_set "$job" "error" "null"
state_set "$job" "diagnosis" "null"

# On any failure past this point, record what broke — with a diagnosis —
# so job.json always reflects the truth about the CURRENT attempt, not a
# stale one.
on_failure() {
  local exit_code=$?
  rm -f "$lock_file"  # always release the lock on exit, success or failure
  if [[ $exit_code -ne 0 ]]; then
    # don't clobber a specific diagnosis a step already wrote for itself
    # (e.g. rough-cut/run.sh) — only fall back to a generic message if
    # nothing more specific is already there
    local existing_diag
    existing_diag="$(state_get "$job" "diagnosis" --default 'null' 2>/dev/null || echo 'null')"
    if [[ "$existing_diag" == "null" ]]; then
      local diagnosis
      diagnosis="$(python3 "${PIPELINE_ROOT}/lib/diagnose.py" "pipeline exited with code ${exit_code}" 2>/dev/null || echo '{}')"
      state_set "$job" "error" "\"pipeline failed at exit code ${exit_code} — check terminal output for details\""
      state_set "$job" "diagnosis" "$diagnosis"
    fi
  fi
}
trap on_failure EXIT

echo "-- [1/7] intake --"
run_step intake bash -c "log 'raw file: $(job_raw_file "$job" || echo none)'"

echo "-- [2/7] rough cut --"
run_step rough_cut "${PIPELINE_ROOT}/skills/rough-cut/run.sh" "$job" "$format"

if [[ "$to_premiere" == true ]]; then
  echo "-- off-ramp: to-premiere --"
  "${PIPELINE_ROOT}/skills/to-premiere/run.sh" "$job" "$format"
  echo "== stopped: handed off to Premiere Pro =="
  exit 0
fi

echo "-- [3/7] graphics (format-specific: ${format}) --"
run_step graphics "${PIPELINE_ROOT}/skills/graphics-plan/run.sh" "$job" "$format"

echo "-- [4/7] second pass (manual review) --"
if [[ "$force" == false ]] && state_step_done "$job" "second_pass" >/dev/null 2>&1; then
  log "[second_pass] already approved, skipping"
elif [[ "$auto_approve" == true ]]; then
  log "[second_pass] --auto-approve set, skipping manual review"
  state_mark "$job" "second_pass" "done"
else
  log "waiting on manual review/incremental re-composite — mark done with:"
  log "  python3 lib/jobstate.py mark ${job} second_pass done"
  echo "== paused: resume with ./run_pipeline.sh ${job} ${format} after Jason approves =="
  exit 0
fi

echo "-- [5/7] captions (format-specific: ${format}) --"
run_step captions "${PIPELINE_ROOT}/skills/embedded-captions/run.sh" "$job" "$format"

if [[ "$skip_music" == false ]]; then
  echo "-- [6/7] background music (optional) --"
  run_step background_music "${PIPELINE_ROOT}/skills/background-music/run.sh" "$job" "$format"
else
  echo "-- [6/7] background music — skipped --"
fi

echo "-- [7/7] export --"
run_step export bash -c "'${PIPELINE_ROOT}/skills/finalize.sh' '${job}' && '${PIPELINE_ROOT}/skills/prune.sh' '${job}'"

# Thumbnail isn't one of the 7 steps (it's a per-format policy: always/skip/
# usually_skip) so it's not gated by job.json state — just run it, it's
# idempotent and cheap.
"${PIPELINE_ROOT}/skills/thumbnail-generator/run.sh" "$job" "$format" || true

echo "== done: outputs/${job}.final.mp4 =="
