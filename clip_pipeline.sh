#!/usr/bin/env bash
set -euo pipefail

# Usage: ./clip_pipeline.sh <job> <format> --clip-length SECONDS --clip-count N \
#          [--content-type podcast|gaming|irl] [--skip-music] [--bonus-clips N] [--keep-raw]
#
# For long-form source (podcast episodes, livestream VODs): runs rough-cut
# ONCE on the full source to get a real transcript, picks the N best
# highlight/hook windows (plus up to --bonus-clips extra strong highlight
# moments beyond N, if there are more worth clipping), then runs the
# normal 7-step pipeline on each window as its own sub-job. No
# re-transcription per clip — the expensive whisper pass happens exactly
# once regardless of clip count.
#
# By default, the big intermediates (the full raw source download and the
# full rough-cut render) are deleted once all clips are extracted — pass
# --keep-raw to keep them around (e.g. if you plan to re-run clip-select
# with different settings without re-downloading/re-transcribing).
#
# Outputs: outputs/<job>__clip01.final.mp4 ... outputs/<job>__clipN.final.mp4

job="${1:?job id required}"
format="${2:?format required}"
shift 2

clip_length=60
clip_count=3
bonus_clips=3   # default on — grab up to 3 extra strong-highlight moments
                # beyond clip_count if the source has more worth clipping
skip_music=false
content_type=""
keep_raw=false
args=("$@")
i=0
while [[ $i -lt ${#args[@]} ]]; do
  case "${args[$i]}" in
    --clip-length) i=$((i+1)); clip_length="${args[$i]}" ;;
    --clip-count)  i=$((i+1)); clip_count="${args[$i]}" ;;
    --bonus-clips) i=$((i+1)); bonus_clips="${args[$i]}" ;;
    --skip-music)  skip_music=true ;;
    --content-type) i=$((i+1)); content_type="${args[$i]}" ;;
    --keep-raw) keep_raw=true ;;
  esac
  i=$((i+1))
done

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/common.sh"
SKILL_DIR="${PIPELINE_ROOT}/skills/clip-select"

format_config="${PIPELINE_ROOT}/formats/${format}.json"
if [[ ! -f "$format_config" ]]; then
  echo "unknown format: $format" >&2
  exit 1
fi

check_disk_space "$job" || exit 1

echo "== clip_pipeline: job=${job} format=${format} clip_length=${clip_length}s clip_count=${clip_count} =="

if [[ ! -f "$(job_dir "$job")/job.json" ]]; then
  raw_file="$(job_raw_file "$job")"
  state_init "$job" "$format" "${raw_file:-}"
fi

if ! state_step_done "$job" rough_cut >/dev/null 2>&1; then
  echo "-- transcribing full source (once) --"
  "${PIPELINE_ROOT}/skills/rough-cut/run.sh" "$job" "$format"
  state_mark "$job" rough_cut done
else
  log "rough-cut already done for '${job}' — reusing existing transcript"
fi

script_path="$(job_dir "$job")/rough-cut/script.json"
rough_cut_video="$(job_dir "$job")/rough-cut/rough_cut.mp4"
clips_json="$(job_dir "$job")/rough-cut/clips.json"

echo "-- selecting ${clip_count} best clip windows (~${clip_length}s each, +${bonus_clips} bonus if strong highlights exist) --"
result="$(python3 "${SKILL_DIR}/select.py" "$script_path" "$clip_length" "$clip_count" "$clips_json" "$bonus_clips")"
log "clip-select: ${result}"

clip_count_actual="$(python3 -c "import json; print(len(json.load(open('${clips_json}'))['clips']))")"
if [[ "$clip_count_actual" == "0" ]]; then
  echo "== no clips selected (no transcript, or no highlight/hook beats found) =="
  exit 1
fi

mapfile -t clip_lines < <(python3 -c "
import json
clips = json.load(open('${clips_json}'))['clips']
for c in clips:
    tag = 'bonus' if c.get('bonus') else 'requested'
    print(f\"{c['id']}\t{c['start']}\t{c['end']}\t{c['score']}\t{tag}\t{c['preview']}\")
")

for line in "${clip_lines[@]}"; do
  IFS=$'\t' read -r clip_id start end score tag preview <<< "$line"
  subjob="${job}__${clip_id}"
  echo "-- ${clip_id} [${tag}]: ${start}s-${end}s (score=${score}) \"${preview}\" --"

  sub_raw_dir="$(job_raw_dir "$subjob")"
  sub_rough_dir="$(job_dir "$subjob")/rough-cut"
  mkdir -p "$sub_raw_dir" "$sub_rough_dir"

  # frame-accurate extraction (re-encode; -ss before -i would be fast but
  # can misalign on a GOP boundary and clip the wrong moment)
  ffmpeg -nostdin -y -i "$rough_cut_video" -ss "$start" -to "$end" \
    -c:v libx264 -preset veryfast -c:a aac \
    "${sub_raw_dir}/source.mp4" -loglevel error
  cp "${sub_raw_dir}/source.mp4" "${sub_rough_dir}/rough_cut.mp4"

  # reuse the parent transcript's overlapping segments instead of
  # re-running whisper on every clip — this is the actual time savings
  python3 -c "
import json
script = json.load(open('${script_path}'))
start, end = ${start}, ${end}
segs = []
for s in script.get('kept_segments', []):
    if s['end'] <= start or s['start'] >= end:
        continue
    segs.append({'start': max(0, s['start']-start), 'end': min(end-start, s['end']-start), 'text': s['text']})
out = {
    'job': '${subjob}', 'transcription_available': True,
    'source_duration_sec': end - start,
    'kept_segments': segs, 'cut_segments': [],
    'script_text': ' '.join(s['text'] for s in segs),
}
json.dump(out, open('${sub_rough_dir}/script.json', 'w'), indent=2)
json.dump({'job': '${subjob}', 'keep': [[s['start'], s['end']] for s in segs], 'cut': []},
          open('${sub_rough_dir}/edl.json', 'w'), indent=2)
"

  if [[ ! -f "$(job_dir "$subjob")/job.json" ]]; then
    state_init "$subjob" "$format" "${sub_raw_dir}/source.mp4"
  fi
  state_mark "$subjob" rough_cut done "{\"note\":\"extracted from ${job} ${clip_id}, reused parent transcript\"}"

  run_args=("${PIPELINE_ROOT}/run_pipeline.sh" "$subjob" "$format")
  [[ "$skip_music" == true ]] && run_args+=(--skip-music)
  [[ -n "$content_type" ]] && run_args+=(--content-type "$content_type")

  "${run_args[@]}" || log "  ${clip_id}: paused for second-pass review (normal) — approve with: python3 lib/jobstate.py mark ${subjob} second_pass done && ./run_pipeline.sh ${subjob} ${format}"
done

if [[ "$keep_raw" == false ]]; then
  # every clip has its own extracted copy already (projects/<job>__clipNN/raw/),
  # so the parent's full-length raw download + full rough-cut render are
  # pure dead weight from here on — for a multi-GB/hour-long source this is
  # the difference between hanging onto tens of GB vs a few small JSON files
  parent_raw="$(job_raw_file "$job")"
  freed=0
  for f in "$parent_raw" "$rough_cut_video"; do
    if [[ -n "$f" && -f "$f" ]]; then
      freed=$((freed + $(stat -f%z "$f" 2>/dev/null || stat -c%s "$f" 2>/dev/null || echo 0)))
      rm -f "$f"
    fi
  done
  rm -rf "$(job_work_dir "$job")"
  log "cleanup: freed ~$((freed / 1024 / 1024))MB (parent raw source + full rough-cut render) — script.json/edl.json/clips.json kept"
else
  log "cleanup: --keep-raw set, leaving parent raw source and rough-cut render in place"
fi

echo "== clip_pipeline done: check outputs/${job}__clip*.final.mp4 =="
