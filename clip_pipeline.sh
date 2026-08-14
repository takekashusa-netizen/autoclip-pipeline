#!/usr/bin/env bash
set -euo pipefail

# Usage: ./clip_pipeline.sh <job> <format> --clip-length SECONDS --clip-count N \
#          [--content-type podcast|gaming|irl] [--skip-music] [--bonus-clips N] [--keep-raw]
#        OR, for highlight-reel montages instead of one-moment-per-clip:
#        ./clip_pipeline.sh <job> <format> --montage-minutes 15 --montage-count N [other flags]
#
# For long-form source (podcast episodes, livestream VODs): runs rough-cut
# ONCE on the full source to get a real transcript, picks the N best
# highlight/hook windows (plus up to --bonus-clips extra strong highlight
# moments beyond N, if there are more worth clipping), then runs the
# normal 7-step pipeline on each window as its own sub-job. No
# re-transcription per clip — the expensive whisper pass happens exactly
# once regardless of clip count.
#
# --montage-minutes switches to montage mode: instead of one short clip
# per highlight moment, packs the best available moments (transcript +
# visual action, same scoring) into --montage-count long highlight-reel
# clips of ~N minutes each — jam-packed with exciting moments back to
# back, not just one longer contiguous window. Each moment is used in at
# most one montage, never duplicated.
#
# By default, the big intermediates (the full raw source download and the
# full rough-cut render) are deleted once all clips are extracted — pass
# --keep-raw to keep them around (e.g. if you plan to re-run clip-select
# with different settings without re-downloading/re-transcribing).
#
# Outputs: outputs/<job>__clip01.final.mp4 ... outputs/<job>__clipN.final.mp4
#      or: outputs/<job>__montage01.final.mp4 ... in montage mode

job="${1:?job id required}"
format="${2:?format required}"
shift 2

clip_length=35
clip_count=3
bonus_clips=3   # default on — grab up to 3 extra strong-highlight moments
                # beyond clip_count if the source has more worth clipping
montage_minutes=0   # 0 = montage mode disabled, use single-window mode
montage_count=3
best_windows_minutes=0   # 0 = best-windows mode disabled
best_windows_count=3
skip_music=false
auto_approve=false
content_type=""
keep_raw=true
# Default flipped tonight after hitting this exact painful scenario
# twice: the OLD default (false) deleted the raw source + rough_cut.mp4
# once clips/montages finished, which permanently prevents ever
# reprocessing that job again (e.g. wanting to try new gunfire-detection
# features on a video you already clipped once). With 400+GB free disk
# being normal today, the space savings aren't worth losing that
# ability. Pass --delete-raw explicitly if you genuinely want the old
# space-saving behavior for a specific job.
args=("$@")
i=0
while [[ $i -lt ${#args[@]} ]]; do
  case "${args[$i]}" in
    --clip-length) i=$((i+1)); clip_length="${args[$i]}" ;;
    --clip-count)  i=$((i+1)); clip_count="${args[$i]}" ;;
    --bonus-clips) i=$((i+1)); bonus_clips="${args[$i]}" ;;
    --montage-minutes) i=$((i+1)); montage_minutes="${args[$i]}" ;;
    --montage) montage_minutes=12 ;;
    --montage-count) i=$((i+1)); montage_count="${args[$i]}" ;;
    --best-windows-minutes) i=$((i+1)); best_windows_minutes="${args[$i]}" ;;
    --best-windows) best_windows_minutes=12 ;;
    --best-windows-count) i=$((i+1)); best_windows_count="${args[$i]}" ;;
    --skip-music)  skip_music=true ;;
    --auto-approve) auto_approve=true ;;
    --content-type) i=$((i+1)); content_type="${args[$i]}" ;;
    --keep-raw) keep_raw=true ;;
    --delete-raw) keep_raw=false ;;
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

if [[ "$montage_minutes" != "0" ]]; then
  echo "== clip_pipeline: job=${job} format=${format} montage_minutes=${montage_minutes} montage_count=${montage_count} =="
elif [[ "$best_windows_minutes" != "0" ]]; then
  echo "== clip_pipeline: job=${job} format=${format} best_windows_minutes=${best_windows_minutes} best_windows_count=${best_windows_count} (continuous, non-overlapping) =="
else
  echo "== clip_pipeline: job=${job} format=${format} clip_length=${clip_length}s clip_count=${clip_count} =="
fi

if [[ ! -f "$(job_dir "$job")/job.json" ]]; then
  raw_file="$(job_raw_file "$job")"
  state_init "$job" "$format" "${raw_file:-}"
fi
# Real bug fixed: doctor.py's auto-resume (via resume_all.sh) treated
# every unfinished job.json the same way and called run_pipeline.sh
# directly on it — WRONG for a job meant to go through clip_pipeline.sh's
# multi-clip flow (transcribe once, split into N clip subjobs). This
# actually happened tonight: it silently started re-processing a
# multi-clip job as if it were a single normal video. This marker lets
# resume_all.sh recognize and skip clip_pipeline-managed jobs, leaving
# them to clip_pipeline.sh's own (already correct) locking/resumability.
state_set "$job" "managed_by" "\"clip_pipeline\""

# Real, urgent bug fixed: clip_pipeline.sh's own top-level processing
# (the initial "transcribe once" step) never acquired the same .lock
# file run_pipeline.sh checks — so doctor.py's new --auto-resume feature
# calling resume_all.sh in parallel saw no lock, assumed the job wasn't
# running, and launched a SECOND full transcription of the same source
# simultaneously. This uses the identical lock convention as
# run_pipeline.sh so ANY invocation path (clip_pipeline.sh directly,
# resume_all.sh, doctor's auto-resume) correctly detects and refuses to
# duplicate an already-running job.
job_lock_file="$(job_dir "$job")/.lock"
if [[ -f "$job_lock_file" ]]; then
  existing_pid="$(cat "$job_lock_file" 2>/dev/null || echo "")"
  if [[ -n "$existing_pid" ]] && kill -0 "$existing_pid" 2>/dev/null; then
    echo "abort: job '${job}' is already running (pid ${existing_pid}) — refusing to start a duplicate clip_pipeline.sh run" >&2
    exit 1
  fi
  echo "note: found a stale lock (pid ${existing_pid} is not running) — proceeding" >&2
fi
echo $$ > "$job_lock_file"
release_job_lock() { rm -f "$job_lock_file"; }
trap release_job_lock EXIT

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

# Real bug fixed: job.json saying "rough_cut: done" was trusted blindly —
# but this pipeline's own cleanup step deletes rough_cut.mp4 (and the raw
# source) once a job's clips/montages finish, by design, to save disk.
# Building a SECOND round of clips/montages from the same job later hit
# exactly this: job.json still said done, but the file was long gone,
# and everything downstream failed with a confusing OpenCV error instead
# of a clear one. Now: verify the file actually exists, and if it
# doesn't but the transcript survived, regenerate it automatically from
# the raw source — same recovery used manually several times tonight,
# now built into the pipeline itself instead of requiring intervention.
if [[ ! -f "$rough_cut_video" ]]; then
  log "rough-cut: job.json says done, but ${rough_cut_video} is missing (likely cleaned up after an earlier clip/montage run) — regenerating"
  raw_source="$(job_raw_file "$job")"
  if [[ -z "$raw_source" || ! -f "$raw_source" ]]; then
    echo "rough-cut: cannot regenerate — raw source is ALSO gone (${raw_source:-none found}). This job needs a fresh download/re-submit." >&2
    exit 1
  fi
  if [[ ! -f "$script_path" ]]; then
    echo "rough-cut: cannot regenerate — script.json is also missing, would need full re-transcription. Resetting rough_cut to pending and re-running from scratch." >&2
    state_mark "$job" rough_cut pending
    "${PIPELINE_ROOT}/skills/rough-cut/run.sh" "$job" "$format"
    state_mark "$job" rough_cut done
  else
    mkdir -p "$(job_dir "$job")/rough-cut" "$(job_work_dir "$job")/rough-cut"
    regen_result="$(python3 -c "
import sys, json
sys.path.insert(0, '${PIPELINE_ROOT}/skills/rough-cut')
from cut_engine import render_cut
script = json.load(open('${script_path}'))
kept = script.get('kept_segments', [])
render_cut('${raw_source}', kept, '${rough_cut_video}', '$(job_work_dir "$job")/rough-cut')
print('regenerated')
" 2>&1)" || { echo "rough-cut: regeneration failed: ${regen_result}" >&2; exit 1; }
    log "rough-cut: ${regen_result} -> ${rough_cut_video}"
  fi
fi

echo "-- analyzing visual content (action/motion detection) --"
visual_json="$(job_dir "$job")/rough-cut/visual-analysis.json"
# Real fix: this used to re-run the expensive (and, on this machine,
# sometimes-interrupted-for-unknown-reasons) visual analysis pass on
# EVERY retry, even when a valid result already existed on disk from an
# earlier successful run — wasting the several minutes it takes AND
# re-risking whatever's killing it, when the answer was already sitting
# right there. Now: reuse a valid cached result if one exists.
cached_valid=false
if [[ -f "$visual_json" ]]; then
  if python3 -c "
import json, sys
try:
    d = json.load(open('${visual_json}'))
    sys.exit(0 if d.get('samples') else 1)
except Exception:
    sys.exit(1)
" 2>/dev/null; then
    cached_valid=true
  fi
fi

if [[ "$cached_valid" == true ]]; then
  log "visual-analysis: reusing existing visual-analysis.json (delete it manually to force a fresh re-analysis)"
elif python3 -c "import cv2" 2>/dev/null; then
  # Real bug fixed: visual analysis is supposed to be optional/best-effort
  # — but under set -euo pipefail, if visual_analysis.py exited non-zero
  # for ANY reason (a crash, an OOM kill, anything), this assignment's own
  # failure silently killed the ENTIRE clip_pipeline.sh run with zero
  # visible error, since the captured stderr never got a chance to print
  # before the script died. The `|| vis_exit=$?` pattern below prevents
  # set -e from treating this as fatal, so a broken/crashed visual
  # analysis degrades to "no visual data" instead of taking down clips
  # that don't even depend on it (transcript-based selection still works).
  vis_exit=0
  vis_result="$(python3 "${PIPELINE_ROOT}/lib/visual_analysis.py" "$rough_cut_video" "$visual_json" --interval 2.0 2>&1)" || vis_exit=$?
  if [[ $vis_exit -ne 0 ]]; then
    log "visual-analysis: FAILED (exit ${vis_exit}) — continuing WITHOUT visual data, transcript-based selection still works. Error was: $(echo "$vis_result" | tail -5)"
    visual_json=""
  else
    log "visual-analysis: ${vis_result}"
  fi
else
  log "visual-analysis: opencv not installed — skipping action-moment detection (pip install opencv-python-headless to enable). Transcript-based selection still works normally."
  visual_json=""
fi

echo "-- analyzing audio content (gunfire/impact detection) --"
audio_json="$(job_dir "$job")/rough-cut/audio-analysis.json"
audio_cached_valid=false
if [[ -f "$audio_json" ]]; then
  if python3 -c "
import json, sys
try:
    d = json.load(open('${audio_json}'))
    sys.exit(0 if 'transients' in d else 1)
except Exception:
    sys.exit(1)
" 2>/dev/null; then
    audio_cached_valid=true
  fi
fi

if [[ "$audio_cached_valid" == true ]]; then
  log "audio-analysis: reusing existing audio-analysis.json (delete it manually to force a fresh re-analysis)"
else
  # same crash-resilience pattern as visual analysis above — a broken
  # audio track or an ffmpeg extraction failure degrades to "no audio
  # data" instead of taking down the whole run
  audio_exit=0
  audio_result="$(python3 "${PIPELINE_ROOT}/lib/audio_analysis.py" "$rough_cut_video" "$audio_json" 2>&1)" || audio_exit=$?
  if [[ $audio_exit -ne 0 ]]; then
    log "audio-analysis: FAILED (exit ${audio_exit}) — continuing WITHOUT audio transient data. Error was: $(echo "$audio_result" | tail -5)"
    audio_json=""
  else
    log "audio-analysis: ${audio_result}"
  fi
fi

if [[ "$best_windows_minutes" != "0" ]]; then
  # Genuinely different mode from montage: montage stitches many small
  # scored fragments together (jump cuts between disconnected moments).
  # This finds the best CONTINUOUS, non-overlapping N-minute stretches
  # and extracts each as ONE single ffmpeg cut — real unbroken footage,
  # no skipping around, straight into its own file in a dedicated folder.
  bw_out_dir="$(job_dir "$job")/best-windows"
  mkdir -p "$bw_out_dir"
  windows_json="${bw_out_dir}/windows.json"
  source_duration="$(python3 -c "import json; d=json.load(open('${script_path}')); print(d.get('source_duration_sec', 0))" 2>/dev/null || echo 0)"

  bw_exit=0
  result="$(python3 "${SKILL_DIR}/best_windows.py" "$script_path" "$visual_json" "$audio_json" "$source_duration" "$best_windows_minutes" "$best_windows_count" "$windows_json" 2>&1)" || bw_exit=$?
  if [[ $bw_exit -ne 0 ]]; then
    echo "best-windows FAILED (exit ${bw_exit}): $(echo "$result" | tail -10)" >&2
    exit 1
  fi
  log "best-windows: ${result}"

  final_out_dir="${PIPELINE_ROOT}/outputs/${job}_best_windows"
  mkdir -p "$final_out_dir"
  # Real bug fixed: this was extracting from rough_cut_video (the
  # ALREADY-CUT, filler-word-removed file — shorter than the original)
  # while best_windows.py computes window positions against the
  # ORIGINAL full-length timeline (source_duration_sec, and every
  # transcript/visual/audio timestamp feeding into it). That mismatch
  # meant window start/end times didn't correspond to real content in
  # rough_cut_video at all — confirmed directly on a real job: window 1
  # came out truncated (218s instead of the intended 720s), windows 2
  # and 3 came out completely empty (262 bytes, ffmpeg seeking past the
  # end of the shorter file). raw_source is the original, uncut video —
  # the same timeline everything else in this feature was computed
  # against, exactly matching how clip/montage extraction already
  # correctly uses the original source, not the cut one.
  raw_source="$(job_raw_file "$job")"
  if [[ -z "$raw_source" || ! -f "$raw_source" ]]; then
    echo "extract-best-windows: raw source not found (was it deleted?) — cannot extract with correct timing. Re-download the source to fix this." >&2
    exit 1
  fi
  ext_exit=0
  ext_result="$(python3 "${SKILL_DIR}/extract_best_windows.py" "$raw_source" "$windows_json" "$final_out_dir" "$job" 2>&1)" || ext_exit=$?
  if [[ $ext_exit -ne 0 ]]; then
    echo "extract-best-windows FAILED (exit ${ext_exit}): $(echo "$ext_result" | tail -10)" >&2
    exit 1
  fi
  log "extract-best-windows: ${ext_result}"
  echo "== best-windows done: check ${final_out_dir}/ for real, continuous, non-overlapping clips =="
  exit 0
fi

echo "-- selecting best moments (montage_minutes=${montage_minutes}) --"
if [[ "$montage_minutes" != "0" ]]; then
  # Same bug class fixed here as visual_analysis.py above — under set -e,
  # an unhandled crash in build_montage.py (bad JSON, an edge case in the
  # candidate data, anything) would silently kill the whole script with
  # zero visible error. Now it surfaces the real error and exits cleanly
  # instead of vanishing.
  bm_exit=0
  result="$(python3 "${SKILL_DIR}/build_montage.py" "$script_path" "$visual_json" "$montage_minutes" "$montage_count" "$clips_json" --audio-path "$audio_json" 2>&1)" || bm_exit=$?
  if [[ $bm_exit -ne 0 ]]; then
    echo "build-montage FAILED (exit ${bm_exit}): $(echo "$result" | tail -10)" >&2
    exit 1
  fi
  log "build-montage: ${result}"
  clip_count_actual="$(python3 -c "import json; print(len(json.load(open('${clips_json}'))['montages']))" 2>&1)" || {
    echo "failed reading clips.json after build-montage: ${clip_count_actual}" >&2
    exit 1
  }
  if [[ "$clip_count_actual" == "0" ]]; then
    echo "== no montages built (no transcript, or no highlight/action beats found) =="
    exit 1
  fi
else
  sel_exit=0
  result="$(python3 "${SKILL_DIR}/clip_select.py" "$script_path" "$clip_length" "$clip_count" "$clips_json" "$bonus_clips" "$visual_json" "$audio_json" 2>&1)" || sel_exit=$?
  if [[ $sel_exit -ne 0 ]]; then
    echo "clip-select FAILED (exit ${sel_exit}): $(echo "$result" | tail -10)" >&2
    exit 1
  fi
  log "clip-select: ${result}"
  clip_count_actual="$(python3 -c "import json; print(len(json.load(open('${clips_json}'))['clips']))" 2>&1)" || {
    echo "failed reading clips.json after clip-select: ${clip_count_actual}" >&2
    exit 1
  }
  if [[ "$clip_count_actual" == "0" ]]; then
    echo "== no clips selected (no transcript, or no highlight/hook beats found) =="
    exit 1
  fi
fi

if [[ "$montage_minutes" != "0" ]]; then
  montage_ids=()
  while IFS= read -r line; do
    [[ -n "$line" ]] && montage_ids+=("$line")
  done < <(python3 -c "
import json
for m in json.load(open('${clips_json}'))['montages']:
    print(m['id'])
")

  for montage_id in "${montage_ids[@]}"; do
    subjob="${job}__${montage_id}"
    # combined into one call + real error handling — two unprotected
    # python3 -c calls here previously, same silent-death risk as
    # everywhere else in this audit if the montage lookup ever failed
    montage_info="$(python3 -c "
import json
try:
    montages = json.load(open('${clips_json}'))['montages']
    m = next(m for m in montages if m['id'] == '${montage_id}')
    print(f\"{len(m['segments'])}\t{m['total_duration']}\")
except Exception as e:
    print(f'ERROR\t{e}')
")"
    IFS=$'\t' read -r seg_count total_dur <<< "$montage_info"
    if [[ "$seg_count" == "ERROR" ]]; then
      echo "failed reading montage '${montage_id}' from clips.json: ${total_dur}" >&2
      continue
    fi
    echo "-- ${montage_id}: ${seg_count} moments, ${total_dur}s total --"

    sub_raw_dir="$(job_raw_dir "$subjob")"
    sub_rough_dir="$(job_dir "$subjob")/rough-cut"
    sub_work_dir="$(job_work_dir "$subjob")/montage"
    mkdir -p "$sub_raw_dir" "$sub_rough_dir" "$sub_work_dir"

    # extract each segment, concat into one continuous montage video —
    # same batching pattern used elsewhere in this pipeline, just applied
    # to hand-picked highlight segments instead of whisper's keep-list
    seg_lines=()
    while IFS= read -r line; do
      [[ -n "$line" ]] && seg_lines+=("$line")
    done < <(python3 -c "
import json
montages = json.load(open('${clips_json}'))['montages']
m = next(m for m in montages if m['id'] == '${montage_id}')
for s in m['segments']:
    print(f\"{s['start']}\t{s['end']}\")
")

    # Real fix: this used to always re-extract every segment from
    # scratch on every retry, and never cleaned old debris — so a run
    # that died partway through (e.g. from an external kill, unrelated
    # to this code) left a mix of THIS run's progress and a DIFFERENT
    # earlier attempt's leftover files at the same path, silently
    # confusing later concat/inspection. Now: stale part files beyond
    # this run's actual segment count get removed, and any part file
    # that already exists AND passes an integrity check is skipped
    # instead of re-extracted — so a retry after a kill picks up where
    # it left off instead of redoing (and re-risking) already-finished
    # work.
    expected_count=${#seg_lines[@]}
    for stale in "${sub_work_dir}"/part_*.mp4; do
      [[ -e "$stale" ]] || continue
      stale_idx=$(basename "$stale" .mp4 | sed 's/part_//' | sed 's/^0*//')
      stale_idx=${stale_idx:-0}
      if [[ "$stale_idx" -ge "$expected_count" ]]; then
        log "  removing stale leftover from a different earlier attempt: $(basename "$stale")"
        rm -f "$stale"
      fi
    done

    part_files=()
    part_idx=0
    for seg_line in "${seg_lines[@]}"; do
      IFS=$'\t' read -r seg_start seg_end <<< "$seg_line"
      part_file="${sub_work_dir}/part_$(printf '%04d' $part_idx).mp4"
      if [[ -f "$part_file" ]] && ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "$part_file" >/dev/null 2>&1; then
        log "  segment ${part_idx}: already extracted and valid, skipping"
      else
        [[ -f "$part_file" ]] && rm -f "$part_file"  # remove a truncated/corrupt leftover before retrying it
        if ! run_with_timeout 120 ffmpeg -nostdin -y -i "$rough_cut_video" -ss "$seg_start" -to "$seg_end" \
          -c:v libx264 -preset veryfast -c:a aac \
          "$part_file" -loglevel error; then
          echo "montage segment ${part_idx} extraction timed out or failed (120s) — likely a corrupted region at ${seg_start}s" >&2
          exit 1
        fi
      fi
      part_files+=("$part_file")
      part_idx=$((part_idx + 1))
    done

    concat_list="${sub_work_dir}/concat.txt"
    : > "$concat_list"
    for pf in "${part_files[@]}"; do
      echo "file '${pf}'" >> "$concat_list"
    done
    if ! run_with_timeout 120 ffmpeg -nostdin -y -f concat -safe 0 -i "$concat_list" -c copy \
      "${sub_raw_dir}/source.mp4" -loglevel error; then
      echo "montage concat timed out or failed (120s)" >&2
      exit 1
    fi
    cp "${sub_raw_dir}/source.mp4" "${sub_rough_dir}/rough_cut.mp4"
    rm -rf "$sub_work_dir"

    # build a synthetic script.json spanning the WHOLE montage, with each
    # segment's text preserved and re-timed to its position in the
    # concatenated output (offset by the cumulative duration of the
    # segments before it) — captions/graphics downstream just see one
    # continuous transcript, no different from a real single-source video
    python3 -c "
import json
montages = json.load(open('${clips_json}'))['montages']
m = next(m for m in montages if m['id'] == '${montage_id}')
segs = []
offset = 0.0
for s in m['segments']:
    dur = s['end'] - s['start']
    segs.append({'start': offset, 'end': offset + dur, 'text': s['text']})
    offset += dur
out = {
    'job': '${subjob}', 'transcription_available': True,
    'source_duration_sec': offset,
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
    state_mark "$subjob" rough_cut done "{\"note\":\"montage of ${seg_count} moments from ${job}\"}"

    run_args=("${PIPELINE_ROOT}/run_pipeline.sh" "$subjob" "$format")
    [[ "$skip_music" == true ]] && run_args+=(--skip-music)
    [[ "$auto_approve" == true ]] && run_args+=(--auto-approve)
    [[ -n "$content_type" ]] && run_args+=(--content-type "$content_type")

    "${run_args[@]}" || log "  ${montage_id}: paused for second-pass review (normal) — approve with: python3 lib/jobstate.py mark ${subjob} second_pass done && ./run_pipeline.sh ${subjob} ${format}"
  done

else

clip_lines=()
while IFS= read -r line; do
  [[ -n "$line" ]] && clip_lines+=("$line")
done < <(python3 -c "
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
  if ! run_with_timeout 120 ffmpeg -nostdin -y -i "$rough_cut_video" -ss "$start" -to "$end" \
    -c:v libx264 -preset veryfast -c:a aac \
    "${sub_raw_dir}/source.mp4" -loglevel error; then
    echo "clip extraction timed out or failed (120s) for ${subjob} — likely a corrupted region at ${start}s" >&2
    exit 1
  fi
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
  [[ "$auto_approve" == true ]] && run_args+=(--auto-approve)
  [[ -n "$content_type" ]] && run_args+=(--content-type "$content_type")

  "${run_args[@]}" || log "  ${clip_id}: paused for second-pass review (normal) — approve with: python3 lib/jobstate.py mark ${subjob} second_pass done && ./run_pipeline.sh ${subjob} ${format}"
done

fi

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

echo "== clip_pipeline done: check outputs/${job}__clip*.final.mp4 or outputs/${job}__montage*.final.mp4 =="
