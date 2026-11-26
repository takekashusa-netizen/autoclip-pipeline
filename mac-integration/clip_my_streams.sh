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
# First run on a fresh Mac: install what the clipper needs (Homebrew asks for your Mac password once).
if ! command -v brew >/dev/null 2>&1; then
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  eval "$(/opt/homebrew/bin/brew shellenv 2>/dev/null || /usr/local/bin/brew shellenv)"
fi
for pkg in ffmpeg tesseract python@3.12; do brew list "$pkg" >/dev/null 2>&1 || brew install "$pkg"; done
if [[ ! -d .venv ]]; then "$(brew --prefix python@3.12)/bin/python3.12" -m venv .venv; fi
PY="${PY:-$PWD/.venv/bin/python}"
"$PY" -m pip install -q --upgrade pip
"$PY" -m pip install -q -r web/requirements.txt -r worker/requirements.txt numpy opencv-python-headless pillow anthropic faster-whisper "yt-dlp>=2025.1"
export PATH="$PWD/.venv/bin:$PATH"
chmod +x *.sh skills/*.sh skills/*/run.sh 2>/dev/null || true
"$PY" worker/owner_streams.py local
DEST="$HOME/Movies/TakeKash Clips"
mkdir -p "$DEST"
find outputs -maxdepth 1 -name 'owner-*.final.mp4' -exec cp -n {} "$DEST"/ \;
echo "Done. Clips are in: $DEST"
open "$DEST" 2>/dev/null || true
