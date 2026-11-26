#!/usr/bin/env bash
# Clip every best moment from all of GtaxZombies' past live streams, on the owner's own Mac.
# Uses the owner's own signed-in Chrome session for YouTube (YouTube refuses downloads from cloud servers).
# Hours with no real audio are skipped. Safe to re-run: finished hours are remembered and skipped.
#
#   ./mac-integration/clip_my_streams.sh            # every past stream (YouTube + Twitch)
#   BROWSER=safari ./mac-integration/clip_my_streams.sh
set -euo pipefail
cd "$(dirname "$0")/.."
export OWNER_COOKIES_BROWSER="${BROWSER:-chrome}"
export OWNER_CHANNELS="${OWNER_CHANNELS:-https://www.youtube.com/@gtaxzombies/streams,https://www.twitch.tv/gtaxzombies/videos?filter=archives}"
export PIPELINE_WHISPER_MODEL="${PIPELINE_WHISPER_MODEL:-small}"
PY="${PY:-python3}"
"$PY" -m pip install -q --upgrade "yt-dlp>=2025.1" >/dev/null
"$PY" worker/owner_streams.py local
DEST="$HOME/Movies/TakeKash Clips"
mkdir -p "$DEST"
find outputs -maxdepth 1 -name 'owner-*.final.mp4' -exec cp -n {} "$DEST"/ \;
echo "Done. Clips are in: $DEST"
open "$DEST" 2>/dev/null || true
