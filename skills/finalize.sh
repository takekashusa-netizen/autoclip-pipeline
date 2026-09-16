#!/usr/bin/env bash
set -euo pipefail
# args: <job>
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../lib/common.sh"

job="$1"

# Walk the pipeline's artifact chain backwards to find the last real output —
# lets finalize work whether or not background-music/captions actually ran
# (e.g. long-form skips captions, --skip-music skips scoring).
for candidate in \
  "$(job_dir "$job")/music-out/scored_cut.mp4" \
  "$(job_dir "$job")/captions/captions_cut.mp4" \
  "$(job_dir "$job")/graphics/graphics_cut.mp4" \
  "$(job_dir "$job")/rough-cut/rough_cut.mp4"
do
  if [[ -f "$candidate" ]]; then
    src="$candidate"
    break
  fi
done

if [[ -z "${src:-}" ]]; then
  echo "finalize: no rendered output found for job '${job}' — did earlier steps run?" >&2
  exit 1
fi

dest="${PIPELINE_ROOT}/outputs/${job}.final.mp4"
mkdir -p "${PIPELINE_ROOT}/outputs"
# Real, permanent fix: TikTok's own current branding guidelines say
# apps must avoid burning logos/watermarks/promotional branding into
# content shared to TikTok - confirmed directly against TikTok's
# documented rules tonight. Set NO_WATERMARK=1 (the interview/vertical
# TikTok-bound path sets this automatically) to skip the burn-in;
# Instagram-bound clips can still keep it since Instagram has no such
# restriction.
watermark="${PIPELINE_ROOT}/assets/gtax_zombies_watermark.png"
if [[ -f "$watermark" && "${NO_WATERMARK:-0}" != "1" ]]; then
  # Pilot fix (2026-09-16 pipeline-speed audit): a real job's timestamps
  # showed this single watermark re-encode taking ~66s — roughly as long
  # as every earlier step combined — because it was software-encoding
  # (libx264) the whole final video just to overlay a small logo.
  # h264_videotoolbox is Mac's hardware encoder, typically 3-8x faster.
  # This can't be tested from the sandboxed device-bridge shell (it's a
  # Linux VM — VideoToolbox is a macOS-only API), so it tries hardware
  # encoding first and automatically falls back to the known-good libx264
  # path on ANY failure (missing encoder, driver issue, etc.) — a broken
  # or unavailable hardware encoder degrades to the old behavior, it
  # never breaks an export. Report back real timing/quality from a live
  # job so the rest of the pipeline's ffmpeg calls can follow suit.
  mkdir -p "${PIPELINE_ROOT}/logs"
  if ffmpeg -nostdin -y -i "$src" -i "$watermark"       -filter_complex "overlay=W-w-24:H-h-24"       -c:v h264_videotoolbox -b:v 8M -pix_fmt yuv420p -color_range tv -c:a copy "$dest"       2>"${PIPELINE_ROOT}/logs/finalize_videotoolbox_attempt.log"; then
    log "finalize: watermark burned in via h264_videotoolbox (hardware encode)"
  else
    log "finalize: h264_videotoolbox unavailable or failed (see logs/finalize_videotoolbox_attempt.log) — falling back to libx264"
    ffmpeg -nostdin -y -i "$src" -i "$watermark"     -filter_complex "overlay=W-w-24:H-h-24"     -c:v libx264 -preset veryfast -pix_fmt yuv420p -color_range tv -c:a copy "$dest"
    log "finalize: watermark burned in from assets/gtax_zombies_watermark.png (software encode)"
  fi
else
  cp "$src" "$dest"
fi
state_set "$job" "artifacts.final_output" "\"outputs/${job}.final.mp4\""
log "finalize: promoted $(basename "$src") -> outputs/${job}.final.mp4"
progress_report "$job" "done"
