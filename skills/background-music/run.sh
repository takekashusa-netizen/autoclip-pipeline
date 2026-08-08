#!/usr/bin/env bash
set -euo pipefail
# args: <job> <format>
SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SKILL_DIR}/../../lib/common.sh"

job="$1"; format="$2"

progress_report "$job" "background_music"

video_in="$(job_dir "$job")/captions/captions_cut.mp4"
if [[ ! -f "$video_in" ]]; then
  video_in="$(job_dir "$job")/graphics/graphics_cut.mp4"
fi
if [[ ! -f "$video_in" ]]; then
  echo "background-music: no video from captions/graphics steps — run those first" >&2
  exit 1
fi

music_dir="$(job_dir "$job")/music"
mkdir -p "$music_dir"
track="$(find "$music_dir" -maxdepth 1 -type f \( -iname '*.mp3' -o -iname '*.wav' -o -iname '*.m4a' \) 2>/dev/null | head -n1 || true)"

out_dir="$(job_dir "$job")/music-out"
mkdir -p "$out_dir"
out_path="${out_dir}/scored_cut.mp4"

if [[ -z "$track" ]]; then
  log "background-music: no track found at projects/${job}/music/ — this step is optional, passing video through unchanged"
  log "background-music: to add a score, drop an mp3/wav/m4a into projects/${job}/music/ and re-run with --force"
  cp "$video_in" "$out_path"
else
  log "background-music: found $(basename "$track") — sidechain ducking under voice + re-normalizing"
  ffmpeg -nostdin -y -i "$video_in" -i "$track" -filter_complex \
    "[1:a]volume=0.35[music];[music][0:a]sidechaincompress=threshold=0.03:ratio=8:attack=5:release=250[ducked];[0:a][ducked]amix=inputs=2:duration=first:dropout_transition=2,loudnorm[aout]" \
    -map 0:v -map "[aout]" -c:v copy -shortest "$out_path" -loglevel error
fi

state_set "$job" "artifacts.scored_video" "\"projects/${job}/music-out/scored_cut.mp4\""
log "background-music: done -> projects/${job}/music-out/scored_cut.mp4"
