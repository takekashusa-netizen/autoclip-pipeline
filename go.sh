#!/usr/bin/env bash
set -uo pipefail

# go.sh <url> [job_name] [--platform tiktok|youtube] [--clip-count N] [--clip-length N] [--content-type TYPE] [--model NAME]
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
# Usage:
#   ./go.sh "https://www.twitch.tv/videos/XXXX"
#   ./go.sh "https://www.twitch.tv/videos/XXXX" myjob123 --platform tiktok
#
# Combined with doctor.py running in the background with --auto-resume
# (and optionally --auto-publish), this is the closest thing to genuinely
# unattended: run this once, and doctor picks up any stall/failure and
# retries automatically — no need to manually watch logs or relaunch.

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

url="${1:?usage: ./go.sh <url> [job_name] [--platform tiktok|youtube] [--clip-count N] [--clip-length N] [--content-type TYPE] [--model NAME]}"
shift

job=""
if [[ $# -gt 0 && "$1" != --* ]]; then
  job="$1"
  shift
fi
[[ -z "$job" ]] && job="job$(date +%s)"

platform="youtube"
clip_count=10
clip_length=""   # resolved from platform below, unless explicitly overridden
content_type="gaming"
model="tiny"   # real finding tonight: small silently failed on real content
               # while tiny worked correctly — this is now the safe default

while [[ $# -gt 0 ]]; do
  case "$1" in
    --platform) shift; platform="$1" ;;
    --clip-count) shift; clip_count="$1" ;;
    --clip-length) shift; clip_length="$1" ;;
    --content-type) shift; content_type="$1" ;;
    --model) shift; model="$1" ;;
  esac
  shift
done

if [[ -z "$clip_length" ]]; then
  if [[ "$platform" == "tiktok" ]]; then
    clip_length=25   # real research finding: 15-30s outperforms longer clips on TikTok specifically
  else
    clip_length=55   # YouTube Shorts sweet spot
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
