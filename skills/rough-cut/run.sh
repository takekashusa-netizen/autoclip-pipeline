#!/usr/bin/env bash
set -euo pipefail
SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SKILL_DIR}/../../lib/common.sh"

job="$1"; format="$2"

raw_video="$(job_raw_file "$job")"
if [[ -z "$raw_video" ]]; then
  echo "rough-cut: no raw file found in $(job_raw_dir "$job")" >&2
  exit 1
fi

work_dir="$(job_work_dir "$job")/rough-cut"
out_dir="$(job_dir "$job")/rough-cut"
audio_path="${work_dir}/audio.wav"
mkdir -p "$work_dir" "$out_dir"

log "rough-cut: extracting audio from $(basename "$raw_video")"
has_audio="$(ffprobe -v error -select_streams a -show_entries stream=index -of csv=p=0 "$raw_video" | head -n1)"
if [[ -z "$has_audio" ]]; then
  log "rough-cut: no audio stream in source - skipping transcription, pass-through only"
  cp "$raw_video" "${out_dir}/rough_cut.mp4"
  python3 -c "
import json
json.dump({'job': '${job}', 'transcription_available': False,
           'note': 'source has no audio stream',
           'kept_segments': [], 'cut_segments': [], 'script_text': ''},
          open('${out_dir}/script.json', 'w'), indent=2)
json.dump({'job': '${job}', 'keep': [], 'cut': []}, open('${out_dir}/edl.json', 'w'), indent=2)
"
else
  ffmpeg -y -i "$raw_video" -vn -ac 1 -ar 16000 "$audio_path" -loglevel error

  mean_db="$(ffmpeg -i "$audio_path" -af volumedetect -f null - 2>&1 \
    | grep -o 'mean_volume: [-0-9.]*' | grep -o '[-0-9.]*' || echo "0")"
  is_silent="$(python3 -c "print('1' if float('${mean_db:-0}' or 0) < -50 else '0')" 2>/dev/null || echo "0")"

  if [[ "$is_silent" == "1" ]]; then
    log "rough-cut: audio track is effectively silent (${mean_db}dB) - skipping transcription, pass-through only"
    cp "$raw_video" "${out_dir}/rough_cut.mp4"
    python3 -c "
import json
json.dump({'job': '${job}', 'transcription_available': False,
           'note': 'audio track present but effectively silent (${mean_db}dB)',
           'kept_segments': [], 'cut_segments': [], 'script_text': ''},
          open('${out_dir}/script.json', 'w'), indent=2)
json.dump({'job': '${job}', 'keep': [], 'cut': []}, open('${out_dir}/edl.json', 'w'), indent=2)
"
  else
    log "rough-cut: transcribing + building EDL"
    result="$(python3 "${SKILL_DIR}/cut_engine.py" "$job" "$raw_video" "$audio_path" "$out_dir" "$work_dir")"
    log "rough-cut: $result"
  fi
fi

state_set "$job" "artifacts.script" "\"projects/${job}/rough-cut/script.json\""
state_set "$job" "artifacts.edl" "\"projects/${job}/rough-cut/edl.json\""
state_set "$job" "artifacts.rough_cut_video" "\"projects/${job}/rough-cut/rough_cut.mp4\""

log "rough-cut: done -> projects/${job}/rough-cut/{rough_cut.mp4,script.json,edl.json}"
