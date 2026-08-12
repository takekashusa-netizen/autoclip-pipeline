#!/usr/bin/env bash
set -euo pipefail
# args: <job> <format>
# Not wired into run_pipeline.sh's main 7 steps (it's not one of the 7 —
# it's called out per-format: "thumb: always/skip/usually skip"). Call
# directly after export, or from your own publish script.
SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SKILL_DIR}/../../lib/common.sh"

job="$1"; format="$2"

thumb_policy="$(format_get "$format" thumbnail)"
if [[ "$thumb_policy" == "skip" ]]; then
  log "thumbnail-generator: format '${format}' policy is 'skip' — nothing to do"
  exit 0
fi
if [[ "$thumb_policy" == "usually_skip" && "${FORCE_THUMBNAIL:-0}" != "1" ]]; then
  log "thumbnail-generator: format '${format}' policy is 'usually_skip' — skipping (set FORCE_THUMBNAIL=1 to override)"
  exit 0
fi

video="${PIPELINE_ROOT}/outputs/${job}.final.mp4"
if [[ ! -f "$video" ]]; then
  echo "thumbnail-generator: outputs/${job}.final.mp4 doesn't exist — run export first" >&2
  exit 1
fi

plan_path="$(job_dir "$job")/graphics/graphics-plan.json"
grab_time="1.0"
if [[ -f "$plan_path" ]]; then
  # prefer the hook beat's midpoint if we have one
  grab_time="$(python3 -c "
import json
try:
    plan = json.load(open('${plan_path}'))
    highlights = [b for b in plan.get('beats', []) if 'highlight' in b.get('tags', [])]
    hooks = [b for b in plan.get('beats', []) if 'hook' in b.get('tags', [])]
    pick = highlights[0] if highlights else (hooks[0] if hooks else None)
    if pick:
        print((pick['start'] + pick['end']) / 2)
    else:
        print(1.0)
except Exception:
    print(1.0)
")"
fi

out_dir="$(job_dir "$job")/thumbnail"
mkdir -p "$out_dir"
out_path="${out_dir}/thumb.jpg"

log "thumbnail-generator: grabbing frame at t=${grab_time}s (hook beat if available)"
if ! timeout 30 ffmpeg -nostdin -y -ss "$grab_time" -i "$video" -frames:v 1 -q:v 2 "$out_path" -loglevel error; then
  echo "thumbnail-generator: grab timed out or failed (30s) — likely a corrupted region near t=${grab_time}s" >&2
  exit 1
fi

state_set "$job" "artifacts.thumbnail" "\"projects/${job}/thumbnail/thumb.jpg\""
log "thumbnail-generator: done -> projects/${job}/thumbnail/thumb.jpg"
