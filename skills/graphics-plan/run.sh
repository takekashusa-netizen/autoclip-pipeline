#!/usr/bin/env bash
set -euo pipefail
# args: <job> <format>
SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SKILL_DIR}/../../lib/common.sh"

job="$1"; format="$2"

progress_report "$job" "graphics"

script_path="$(job_dir "$job")/rough-cut/script.json"
rough_cut="$(job_dir "$job")/rough-cut/rough_cut.mp4"
if [[ ! -f "$script_path" || ! -f "$rough_cut" ]]; then
  echo "graphics-plan: no rough-cut output — run rough-cut first" >&2
  exit 1
fi

gfx_style="$(format_get "$format" graphics.style)"
gfx_preset="$(format_get "$format" graphics.preset)"
reframe="$(format_get "$format" graphics.reframe)"
[[ -z "$reframe" ]] && reframe="crop"
# CONTENT_TYPE env overrides the format's default reframe strategy — gaming
# footage needs letterbox (no crop) so HUD/killfeed/minimap survives, no
# matter which aspect-ratio format was picked.
if [[ "${CONTENT_TYPE:-}" == "gaming" ]]; then
  reframe="letterbox"
fi
width="$(format_get "$format" fmt.resolution.0)"
height="$(format_get "$format" fmt.resolution.1)"
log "graphics-plan: reading script from rough-cut (no re-transcription)"
log "graphics-plan: style='${gfx_style}' preset='${gfx_preset}' reframe='${reframe}' target=${width}x${height}"

out_dir="$(job_dir "$job")/graphics"
mkdir -p "$out_dir"

log "graphics-plan: planning beats"
beat_result="$(python3 "${SKILL_DIR}/beat_planner.py" "$script_path" "$out_dir/graphics-plan.json")"
log "graphics-plan: $beat_result"

# Face-tracking crop: only attempted when a visual-analysis.json already
# exists (produced by clip_pipeline.sh's montage/clip-select path, or by
# running lib/visual_analysis.py directly) — this is intentionally
# opt-in, not something graphics-plan runs on its own, since sampling a
# full video's frames is real extra work not every job needs.
face_track_json=""
visual_json="$(job_dir "$job")/rough-cut/visual-analysis.json"
if [[ -f "$visual_json" && "$reframe" == "crop" ]]; then
  ft_candidate="${out_dir}/face-track.json"
  ft_exit=0
  ft_result="$(python3 "${PIPELINE_ROOT}/lib/face_tracking.py" "$visual_json" "$ft_candidate" 2>&1)" || ft_exit=$?
  if [[ $ft_exit -eq 0 ]]; then
    ft_usable="$(python3 -c "import json; print(json.loads('''$ft_result''').get('usable', False))" 2>/dev/null || echo "False")"
    if [[ "$ft_usable" == "True" ]]; then
      log "graphics-plan: face-tracking data usable — using dynamic crop instead of static center-crop (${ft_result})"
      face_track_json="$ft_candidate"
    else
      log "graphics-plan: not enough face detection to bother with face-tracking crop — using standard center-crop"
    fi
  else
    log "graphics-plan: face-tracking computation failed (exit ${ft_exit}) — falling back to standard center-crop. Error: $(echo "$ft_result" | tail -3)"
  fi
fi

log "graphics-plan: rendering (reframe + beat cards) via engine stand-in"
render_result="$(python3 "${SKILL_DIR}/render.py" "$rough_cut" "$out_dir/graphics-plan.json" "$width" "$height" "$gfx_style" "$out_dir/graphics_cut.mp4" "$reframe" "$face_track_json")"
log "graphics-plan: $render_result"

state_set "$job" "artifacts.graphics_plan" "\"projects/${job}/graphics/graphics-plan.json\""
state_set "$job" "artifacts.graphics_cut_video" "\"projects/${job}/graphics/graphics_cut.mp4\""

log "graphics-plan: done -> projects/${job}/graphics/{graphics-plan.json,graphics_cut.mp4}"
