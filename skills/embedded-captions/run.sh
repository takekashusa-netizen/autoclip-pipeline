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

# Real, permanent fix: this used to burn captions via ffmpeg's `ass=`
# filter — confirmed on the production machine that this ffmpeg build
# has neither `ass`, `subtitles`, nor `drawtext` compiled in at all
# (same missing-optional-library class of issue as the earlier drawtext
# fix, just a different filter). Now uses the same PIL+overlay approach
# that already fixed beat-card captions, extended to the full
# transcript — no dependency on any of those optional ffmpeg filters.
overlay_exit=0
result="$(python3 "${PIPELINE_ROOT}/lib/caption_overlay.py" "$graphics_video" "$script_path" "$corrections" "${out_dir}/captions_cut.mp4" "$width" "$height" "$position" 2>&1)" || overlay_exit=$?
if [[ $overlay_exit -ne 0 ]]; then
  echo "caption_overlay.py FAILED (exit ${overlay_exit}): $(echo "$result" | tail -10)" >&2
  exit 1
fi
log "embedded-captions: ${result}"

state_set "$job" "artifacts.captions_video" "\"projects/${job}/captions/captions_cut.mp4\""
log "embedded-captions: done -> projects/${job}/captions/captions_cut.mp4"
