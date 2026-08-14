#!/usr/bin/env bash
set -uo pipefail

# go.sh <url> [job_name] [--platform tiktok|youtube|longform] [--clip-count N] [--clip-length N] [--content-type TYPE] [--model NAME]
#
# The actual "one button" — combines what's currently two separate manual
# steps (fetch_url.py, then safe_run.sh ./clip_pipeline.sh) into one
# command, with sensible defaults baked in from tonight's real findings
# (tiny whisper model — proven to work reliably on real content when
# small silently failed; gaming content type; auto-approve so it never
# pauses waiting for a manual review step).
#
# --platform sets a real, research-backed clip-length default: TikTok's
# algorithm rewards completion rate over length, and 15-30s clips
# consistently outperform longer ones from the same footage; YouTube
# Shorts' own sweet spot is closer to 30-60s. Pass --clip-length
# explicitly to override either default.
#
# --platform longform is a genuinely different mode: real, continuous,
# non-overlapping 10+ minute segments (best-windows mode — the actual
# highest-scoring unbroken stretches of the source), NOT montage mode
# (which stitches many small fragments together with jump cuts —
# explicitly retired as the default per an earlier decision). Each
# segment is a single real cut, not a compilation of disconnected clips.
#
# Usage:
#   ./go.sh "https://www.twitch.tv/videos/XXXX"
#   ./go.sh "https://www.twitch.tv/videos/XXXX" myjob123 --platform tiktok
#   ./go.sh "https://www.twitch.tv/videos/XXXX" myjob123 --platform longform --clip-count 3
#
# Combined with doctor.py running in the background with --auto-resume
# (and optionally --auto-publish), this is the closest thing to genuinely
# unattended: run this once, and doctor picks up any stall/failure and
# retries automatically — no need to manually watch logs or relaunch.

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

url="${1:?usage: ./go.sh <url> [job_name] [--platform tiktok|youtube|longform] [--clip-count N] [--clip-length N] [--content-type TYPE] [--model NAME]}"
shift

job=""
if [[ $# -gt 0 && "$1" != --* ]]; then
  job="$1"
  shift
fi
[[ -z "$job" ]] && job="job$(date +%s)"

platform="longform"   # default mode per explicit preference — 10+ min continuous segments, not short clips, unless --platform tiktok/youtube is explicitly requested
clip_count=10
clip_length=""   # resolved from platform below, unless explicitly overridden
content_type="gaming"
model="tiny"   # real finding tonight: small silently failed on real content
               # while tiny worked correctly — this is now the safe default
longform_minutes=12   # real minimum-viable length for the longform platform, override with --clip-length

while [[ $# -gt 0 ]]; do
  case "$1" in
    --platform) shift; platform="$1" ;;
    --clip-count) shift; clip_count="$1" ;;
    --clip-length) shift; clip_length="$1"; longform_minutes="$1" ;;
    --content-type) shift; content_type="$1" ;;
    --model) shift; model="$1" ;;
  esac
  shift
done

if [[ "$platform" == "longform" ]]; then
  if [[ "$longform_minutes" -lt 10 ]]; then
    longform_minutes=10   # real floor — "10+ minutes" was the actual ask, never go below it silently
  fi
  echo "== go.sh: job='${job}' url='${url}' platform='longform' (${clip_count} real continuous segments, ${longform_minutes}+ min each) =="
  echo "== downloading =="
  if ! python3 "${ROOT}/lib/fetch_url.py" "$job" "$url"; then
    echo "go.sh: download failed — see output above" >&2
    exit 1
  fi
  echo "== launching best-windows pipeline (model=${model}, content-type=${content_type}) =="
  PIPELINE_WHISPER_MODEL="$model" "${ROOT}/safe_run.sh" "${ROOT}/clip_pipeline.sh" "$job" long-form-youtube \
    --best-windows-minutes "$longform_minutes" --best-windows-count "$clip_count" \
    --content-type "$content_type" --auto-approve --skip-music
  echo ""
  echo "== launched. real, continuous, non-overlapping ${longform_minutes}+ min segments — check outputs/${job}_best_windows/ when done =="
  exit 0
fi

if [[ -z "$clip_length" ]]; then
  if [[ "$platform" == "tiktok" ]]; then
    clip_length=25   # real research finding: 15-30s outperforms longer clips on TikTok specifically
  else
    clip_length=35   # real research-backed range, but clearly away from a minute per explicit preference
  fi
fi

echo "== go.sh: job='${job}' url='${url}' platform='${platform}' =="
echo "== downloading =="
if ! python3 "${ROOT}/lib/fetch_url.py" "$job" "$url"; then
  echo "go.sh: download failed — see output above" >&2
  exit 1
fi

echo "== launching clip pipeline (model=${model}, ${clip_count} clips of ${clip_length}s, content-type=${content_type}) =="
PIPELINE_WHISPER_MODEL="$model" "${ROOT}/safe_run.sh" "${ROOT}/clip_pipeline.sh" "$job" short-tiktok-raw \
  --clip-length "$clip_length" --clip-count "$clip_count" \
  --content-type "$content_type" --auto-approve --skip-music

echo ""
echo "== launched. this is now genuinely fire-and-forget if doctor.py --auto-resume is running: =="
echo "==   check status anytime:  python3 summarize_clips.py ${job} =="
echo "==   check if still running: ps aux | grep clip_pipeline | grep -v grep =="
