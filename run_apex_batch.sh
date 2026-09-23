#!/usr/bin/env bash
# Runs the full highlight-extraction pipeline on all 20 recovered Apex
# Legends source clips (staged in projects/apex_*/raw/ as symlinks back
# to Downloads/recovered_clips/). For each source, clip_pipeline.sh runs
# rough-cut transcription once, picks the best highlight window(s), and
# renders finished, captioned, watermarked clips to outputs/.
#
# short-tiktok-raw + gaming content-type = letterboxed (HUD-safe), 30s
# clips tuned for TikTok's algorithm (per go.sh's own documented
# research). 2 clips per source + up to 3 bonus clips if a source has
# more highlight-worthy moments than that.
#
# --auto-approve skips the manual review pause so this can run
# unattended end to end. doctor.py's background auto-resume (already
# running) will retry any job that stalls or crashes.
#
# Real incident fixed 2026-09-17: job 1 hung for 9+ hours inside
# visual_analysis.py's OpenCV frame-seeking (a known-flaky step per
# clip_pipeline.sh's own comments) with zero error, silently blocking
# the entire 20-job batch. Two independent fixes:
#  1. clip_pipeline.sh itself now wraps visual-analysis and
#     audio-analysis in run_with_timeout, so that specific known cause
#     can't hang again (real fix, addresses the actual bug).
#  2. This script also puts a hard wall-clock ceiling around each
#     WHOLE job below, as a second line of defense against any other,
#     not-yet-seen hang: enables job control (set -m) so the
#     backgrounded clip_pipeline.sh run gets its own process group, and
#     on timeout kills the entire group (kill -- -PID), not just the
#     top-level shell PID — a plain `kill` on just the parent would
#     leave any ffmpeg/whisper child process it spawned running
#     unsupervised in the background. 40 minutes is generous for a full
#     7-step run on a 3-10 min source clip, even with model-load
#     overhead, but still bounded.
set -uo pipefail
set -m   # job control on, so the backgrounded job below gets its own process group
cd "$(dirname "${BASH_SOURCE[0]}")"
mkdir -p logs
LOG="logs/apex_batch_$(date +%Y%m%d_%H%M%S).log"
echo "Logging to $LOG"
PER_JOB_TIMEOUT_SEC=2400

run_job_with_hard_timeout() {
  local timeout_sec="$1"; shift
  "$@" &
  local pid=$!
  local elapsed=0
  while kill -0 "$pid" 2>/dev/null; do
    sleep 2
    elapsed=$((elapsed + 2))
    if [[ "$elapsed" -ge "$timeout_sec" ]]; then
      echo "  (hard timeout hit - killing process group $pid and everything under it)"
      kill -9 -- "-$pid" 2>/dev/null
      kill -9 "$pid" 2>/dev/null
      wait "$pid" 2>/dev/null
      return 124
    fi
  done
  wait "$pid" 2>/dev/null
  return $?
}

while IFS= read -r job; do
  [[ -z "$job" ]] && continue
  echo "=== $(date '+%H:%M:%S') starting $job (max ${PER_JOB_TIMEOUT_SEC}s) ===" | tee -a "$LOG"
  run_job_with_hard_timeout "$PER_JOB_TIMEOUT_SEC" ./clip_pipeline.sh "$job" short-tiktok-raw \
    --content-type gaming \
    --clip-length 30 \
    --clip-count 2 \
    --auto-approve \
    >> "$LOG" 2>&1
  status=$?
  if [[ $status -eq 0 ]]; then
    echo "=== $(date '+%H:%M:%S') $job DONE ===" | tee -a "$LOG"
  elif [[ $status -eq 124 ]]; then
    echo "=== $(date '+%H:%M:%S') $job TIMED OUT after ${PER_JOB_TIMEOUT_SEC}s - killed (whole process group), moving on. doctor.py will retry it ===" | tee -a "$LOG"
  else
    echo "=== $(date '+%H:%M:%S') $job FAILED (exit $status) - doctor.py will retry it ===" | tee -a "$LOG"
  fi
done < apex_batch_jobs.txt

echo "ALL 20 JOBS SUBMITTED. Check outputs/ for finished clips, or logs/apex_batch_*.log for progress." | tee -a "$LOG"
