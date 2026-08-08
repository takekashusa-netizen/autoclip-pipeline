#!/usr/bin/env bash
set -euo pipefail

# Usage: ./run_pipeline.sh <job> <format> [--skip-music] [--to-premiere] [--force] [--content-type podcast|gaming|irl]
#   job     job id, used for projects/<job>/... and outputs/<job>.final.mp4
#   format  one of: short-explainer | short-tiktok-raw | long-form-youtube
#   --force  re-run steps even if job.json says they're already done
#   --content-type  overrides the format's default reframe strategy —
#                   'gaming' forces letterbox (no crop) so HUD/killfeed
#                   survives; defaults to the format's own content_type

job="${1:?job id required}"
format="${2:?format required (short-explainer|short-tiktok-raw|long-form-youtube)}"
shift 2

skip_music=false
to_premiere=false
force=false
content_type=""
args=("$@")
i=0
while [[ $i -lt ${#args[@]} ]]; do
  case "${args[$i]}" in
    --skip-music) skip_music=true ;;
    --to-premiere) to_premiere=true ;;
    --force) force=true ;;
    --content-type) i=$((i+1)); content_type="${args[$i]}" ;;
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
