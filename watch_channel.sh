#!/usr/bin/env bash
set -uo pipefail
# deliberately NOT set -e — one bad video shouldn't kill the whole watch loop

# Usage: ./watch_channel.sh <channel_url> [--format FMT] [--clip-length N]
#          [--clip-count N] [--content-type TYPE] [--interval SECONDS]
#
# Polls a channel for new videos and auto-clips each new one — no Celery/
# Redis required, just run this detached:
#   nohup ./watch_channel.sh https://youtube.com/@yourchannel --content-type gaming > watch.log 2>&1 &
#
# Already-processed video IDs are tracked in watch_seen.json so restarting
# this script never reprocesses the same video. Finished clips land in
# outputs/clips/<date>_<video-title>/01.mp4, 02.mp4, ... via
# lib/organize_output.py — not loose job-hash-named files.

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${ROOT}/lib/common.sh"

channel_url="${1:?channel URL required}"
shift

format="short-tiktok-raw"
clip_length=60
clip_count=3
content_type=""
interval=900  # 15 min default poll
model="tiny"  # real finding tonight: small silently failed on real
              # content while tiny worked correctly — safe default here
args=("$@")
i=0
while [[ $i -lt ${#args[@]} ]]; do
  case "${args[$i]}" in
    --format) i=$((i+1)); format="${args[$i]}" ;;
    --clip-length) i=$((i+1)); clip_length="${args[$i]}" ;;
    --clip-count) i=$((i+1)); clip_count="${args[$i]}" ;;
    --content-type) i=$((i+1)); content_type="${args[$i]}" ;;
    --interval) i=$((i+1)); interval="${args[$i]}" ;;
    --model) i=$((i+1)); model="${args[$i]}" ;;
  esac
  i=$((i+1))
done

seen_file="${ROOT}/watch_seen.json"
[[ -f "$seen_file" ]] || echo '[]' > "$seen_file"

log "watch_channel: watching ${channel_url} (poll every ${interval}s, format=${format}, ${clip_count}x${clip_length}s clips)"

while true; do
  videos_json="$(python3 "${ROOT}/lib/list_channel_videos.py" "$channel_url" --max 15)"
  err="$(python3 -c "import json,sys; d=json.loads(sys.argv[1]); print(d.get('error',''))" "$videos_json" 2>/dev/null)"
  if [[ -n "$err" ]]; then
    log "watch_channel: couldn't list channel videos — ${err}"
    sleep "$interval"
    continue
  fi

  new_count=0
  new_videos=()
  while IFS= read -r line; do
    [[ -n "$line" ]] && new_videos+=("$line")
  done < <(python3 -c "
import json
seen = set(json.load(open('${seen_file}')))
data = json.loads('''${videos_json}''')
for v in data.get('videos', []):
    if v['id'] not in seen:
        print(f\"{v['id']}\t{v['url']}\t{v['title']}\")
")

  for line in "${new_videos[@]}"; do
    [[ -z "$line" ]] && continue
    IFS=$'\t' read -r vid url title <<< "$line"
    job="watch_${vid}"
    log "watch_channel: new video — \"${title}\" (${vid})"

    fetch_result="$(python3 "${ROOT}/lib/fetch_url.py" "$job" "$url" 2>&1)"
    fetch_err="$(python3 -c "import json,sys; d=json.loads(sys.argv[1]); print(d.get('error',''))" "$fetch_result" 2>/dev/null || echo "")"
    if [[ -n "$fetch_err" ]]; then
      log "watch_channel: download failed for ${vid} — ${fetch_err} (will retry next poll)"
      continue
    fi

    clip_args=("${ROOT}/clip_pipeline.sh" "$job" "$format"
               "--clip-length" "$clip_length" "--clip-count" "$clip_count"
               "--auto-approve" "--skip-music")
    [[ -n "$content_type" ]] && clip_args+=(--content-type "$content_type")

    if PIPELINE_WHISPER_MODEL="$model" "${clip_args[@]}" > "${ROOT}/logs/${job}.log" 2>&1; then
      log "watch_channel: clipped \"${title}\" — organizing output"
      python3 "${ROOT}/lib/organize_output.py" "$job" --title "$title" || \
        log "watch_channel: clip succeeded but organize step failed — check outputs/${job}__clip*.final.mp4 directly"
    else
      log "watch_channel: clip_pipeline.sh failed for ${vid} — check logs/${job}.log (will not retry automatically; fix and resume manually)"
    fi

    # mark seen regardless of success/failure — a genuinely broken video
    # shouldn't be retried every single poll forever; check logs/ if it
    # needs manual attention
    python3 -c "
import json
seen = json.load(open('${seen_file}'))
seen.append('${vid}')
json.dump(seen, open('${seen_file}', 'w'))
"
    new_count=$((new_count + 1))
  done

  if [[ "$new_count" -eq 0 ]]; then
    log "watch_channel: no new videos, checking again in ${interval}s"
  fi
  sleep "$interval"
done
