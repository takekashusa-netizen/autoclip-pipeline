#!/usr/bin/env bash
set -euo pipefail
# args: <job> <format>
SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SKILL_DIR}/../../lib/common.sh"

job="$1"; format="$2"

progress_report "$job" "captions"

captions_enabled="$(format_get "$format" captions.enabled)"
if [[ "$captions_enabled" != "True" && "$captions_enabled" != "true" ]]; then
  log "embedded-captions: format '${format}' has captions disabled (e.g. long-form relies on YT CC) — skipping"
  exit 0
fi

script_path="$(job_dir "$job")/rough-cut/script.json"
graphics_video="$(job_dir "$job")/graphics/graphics_cut.mp4"
if [[ ! -f "$script_path" || ! -f "$graphics_video" ]]; then
  echo "embedded-captions: missing rough-cut/graphics output — run those steps first" >&2
  exit 1
fi

position="$(format_get "$format" captions.position)"
width="$(format_get "$format" fmt.resolution.0)"
height="$(format_get "$format" fmt.resolution.1)"
log "embedded-captions: reusing rough-cut's word timings (no re-transcription)"
log "embedded-captions: position='${position}' target=${width}x${height}"

out_dir="$(job_dir "$job")/captions"
mkdir -p "$out_dir"
corrections="${PIPELINE_ROOT}/presets/caption-corrections.json"
ass_path="${out_dir}/captions.ass"

result="$(python3 "${SKILL_DIR}/build_ass.py" "$script_path" "$corrections" "$ass_path" "$width" "$height" "$position")"
log "embedded-captions: ${result}"

caption_lines="$(python3 -c "import json; print(json.loads('$result')['caption_lines'])")"
if [[ "$caption_lines" == "0" ]]; then
  log "embedded-captions: no caption lines (no transcript available) — copying graphics_cut.mp4 through unburned"
  cp "$graphics_video" "${out_dir}/captions_cut.mp4"
else
  log "embedded-captions: burning in on-beat"
  ffmpeg -nostdin -y -i "$graphics_video" -vf "ass=${ass_path}" -c:a copy "${out_dir}/captions_cut.mp4" -loglevel error
fi

state_set "$job" "artifacts.captions_video" "\"projects/${job}/captions/captions_cut.mp4\""
log "embedded-captions: done -> projects/${job}/captions/{captions.ass,captions_cut.mp4}"
