#!/usr/bin/env bash
# fix_pipeline_venv.sh
#
# Real, permanent fix for why dashboard.py and the poller have been dead
# since the 2026-09-22 kernel panic: their launchd services point
# python3 at autoclip-pipeline/venv/bin/python3, but that folder turned
# out to be the Impacket pentesting toolkit's venv (mimikatz,
# secretsdump, ntlmrelayx, etc — confirmed via its site-packages and
# share/doc/impacket), not the pipeline's own environment. It has no
# bin/python3 at all, so launchd has just been failing to start both
# services over and over with "No such file or directory".
#
# A second stray venv at ~/venv was checked too and is also not it —
# it's an essentially-empty Python 3.9 venv (just pip/setuptools, no
# real packages), unrelated to either.
#
# This script builds a real, correctly-populated venv at
# autoclip-pipeline/venv_pipeline (a new name, so it can never collide
# with the Impacket venv again), installs exactly the third-party
# packages this codebase actually imports (verified by grepping every
# .py file in the repo and lib/), then finds every takekash-related
# launchd plist, backs each one up, repoints its python3 path at the
# new venv, and restarts the service — verifying the dashboard actually
# responds afterward rather than just assuming the restart worked.
#
# Run this yourself in Terminal on the Mac (needs launchctl, which
# isn't reachable from Claude's sandboxed device-bridge shell):
#   cd ~/autoclip-pipeline && bash fix_pipeline_venv.sh

set -euo pipefail
cd "$(dirname "$0")"

echo "== 1/5: picking a Python that actually has prebuilt wheels for these packages =="
# Real bug from the first run: plain `python3` on this Mac now resolves to
# 3.14 (very new), and faster-whisper pulls in `av` (PyAV) and
# ctranslate2, which don't have prebuilt wheels for 3.14 yet - pip fell
# back to compiling PyAV's Cython source, which itself doesn't build
# cleanly against 3.14's stricter C-API (the "noexcept" errors). Picking
# an older, well-supported interpreter avoids the source build entirely
# instead of fighting the Cython errors directly. Prefers 3.12 first,
# since that's confirmed already installed on this Mac (it's what the
# unrelated Impacket venv was built with).
PYBIN=""
for v in python3.12 python3.11 python3.10 python3.13 python3.9; do
  if command -v "$v" >/dev/null 2>&1; then
    PYBIN="$v"
    break
  fi
done
if [[ -z "$PYBIN" ]]; then
  echo "no python3.9-3.13 found on PATH, falling back to plain python3 (may hit the same wheel issue)" >&2
  PYBIN="python3"
fi
echo "  using: $PYBIN ($($PYBIN --version 2>&1))"

echo "== 2/5: building fresh venv at ./venv_pipeline =="
if [[ -d venv_pipeline ]]; then
  echo "venv_pipeline already exists — removing it first for a clean build"
  rm -rf venv_pipeline
fi
"$PYBIN" -m venv venv_pipeline
source venv_pipeline/bin/activate
pip install --upgrade pip --quiet

echo "== 3/5: installing the real dependencies this pipeline actually imports =="
# anthropic          - lib/generate_clip_metadata.py (real, grounded per-clip captions)
# Pillow             - image/thumbnail handling
# faster-whisper     - real transcription (graphics-plan.json beats, captions)
# google-api-python-client, google-auth*  - Drive + YouTube API access
# numpy              - audio/video analysis
# requests           - general HTTP (TikTok/Instagram publish, etc.)
PKGS=(anthropic Pillow faster-whisper google-api-python-client
      google-auth google-auth-httplib2 google-auth-oauthlib numpy requests)
# --prefer-binary: take a wheel over a source build whenever one exists
# for this interpreter, even if pip would otherwise prefer a newer sdist.
# This is the real, permanent fix for the failure mode seen in the first
# run, not just a workaround for this one Python version.
if ! pip install --prefer-binary --quiet "${PKGS[@]}"; then
  echo "  --prefer-binary install failed — retrying wheels-only (no source builds at all)" >&2
  pip install --only-binary=:all: --quiet "${PKGS[@]}"
fi

echo "== 4/6: verifying dashboard.py's own imports actually resolve now =="
# Run the exact check that matters: can dashboard.py itself be imported?
# dashboard.py does its own sys.path.insert(0, ROOT/lib) at module load
# time (line 38) before importing its local modules (channel_watcher,
# content_filter, generate_clip_metadata, instagram_publish,
# originality_boost, thumbnail_brand, tiktok_publish, youtube_publish —
# all of which live in lib/, not the repo root). The previous version of
# this check hand-rolled its own AST-based import scan that never added
# lib/ to sys.path, so it always false-flagged every one of those as
# "missing" even when they imported fine for real. Just importing
# dashboard.py directly (safe: its server-start code is behind
# `if __name__ == "__main__":`) is both simpler and actually correct.
if python3 -c "import dashboard" 2>/tmp/_dashboard_import_check.log; then
  echo "dashboard.py imports OK"
else
  echo "STILL FAILING — dashboard.py itself could not be imported:" >&2
  cat /tmp/_dashboard_import_check.log >&2
  exit 1
fi

deactivate

echo "== 5/6: making sure the dashboard launchd service actually exists =="
# Real finding from this Mac (not an assumption): com.takekash.dashboard.plist
# does not exist anywhere (checked ~/Library/LaunchAgents, /Library/LaunchAgents,
# /Library/LaunchDaemons) and nothing matching "takekash" is loaded in launchctl
# either -- so there is nothing to repoint. Past runs assumed the plist already
# existed; this creates it fresh instead, grounded in dashboard.py's own real
# CLI (`--port 8765`, confirmed from its argparse block) rather than guessing.
#
# The poller (com.takekash.poller) is NOT recreated here: cloud_poller.py
# hard-requires QUEUE_SECRET at startup and that value lived only in the now-
# missing plist's EnvironmentVariables -- it is not recoverable from this repo.
# Get that secret from wherever it was originally set (Netlify site env vars,
# a password manager, etc.) and re-add it by hand, or ask for help wiring up
# a fresh com.takekash.poller.plist once you have it.
LAUNCH_DIR="$HOME/Library/LaunchAgents"
mkdir -p "$LAUNCH_DIR"
DASH_PLIST="$LAUNCH_DIR/com.takekash.dashboard.plist"
NEW_PY="$(pwd)/venv_pipeline/bin/python3"
DASH_PY="$(pwd)/dashboard.py"

if [[ -f "$DASH_PLIST" ]]; then
  cp "$DASH_PLIST" "${DASH_PLIST}.bak-$(date +%Y%m%d%H%M%S)"
  echo "  -- com.takekash.dashboard: existing plist backed up, repointing python3 --"
  /usr/bin/sed -i '' "s#[^<]*autoclip-pipeline/venv/bin/python3#${NEW_PY}#g" "$DASH_PLIST"
  /usr/bin/sed -i '' "s#[^<]*/venv/bin/python3#${NEW_PY}#g" "$DASH_PLIST"
else
  echo "  -- com.takekash.dashboard: no plist found, creating a fresh one --"
  cat > "$DASH_PLIST" << PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.takekash.dashboard</string>
    <key>ProgramArguments</key>
    <array>
        <string>${NEW_PY}</string>
        <string>${DASH_PY}</string>
        <string>--port</string>
        <string>8765</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$(pwd)</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>$(pwd)/dashboard.log</string>
    <key>StandardErrorPath</key>
    <string>$(pwd)/dashboard.log</string>
</dict>
</plist>
PLISTEOF
fi
echo "  now points at: $(grep -A1 -i python3 "$DASH_PLIST" | head -2 | tail -1 | sed 's/^\s*//')"

echo "== 6/6: restarting the services and verifying they're actually up =="
for plist in "$LAUNCH_DIR"/com.takekash.*.plist; do
  [[ -f "$plist" ]] || continue
  label=$(basename "$plist" .plist)
  launchctl load "$plist" 2>/dev/null
  launchctl kickstart -k "gui/$(id -u)/${label}" 2>/dev/null || {
    launchctl unload "$plist" 2>/dev/null || true
    launchctl load "$plist"
  }
done

echo "  waiting for dashboard to respond on :8765 ..."
up=false
for _ in $(seq 1 20); do
  if curl -sf "http://localhost:8765/api/jobs" > /dev/null 2>&1; then
    up=true
    break
  fi
  sleep 1
done

if [[ "$up" == "true" ]]; then
  echo "== CONFIRMED: dashboard is up and responding =="
else
  echo "== dashboard still not responding — check dashboard.log for the real error == " >&2
  tail -30 dashboard.log >&2
  exit 1
fi

echo ""
echo "Done. venv_pipeline is the pipeline's real environment going forward;"
echo "the old autoclip-pipeline/venv (Impacket toolkit) was left untouched."
