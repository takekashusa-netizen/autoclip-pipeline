#!/usr/bin/env python3
"""
lib/list_channel_videos.py <channel_url> [--max N]

Flat-playlist extraction of a channel's recent videos — just IDs/titles/
upload dates, no per-video download. Shared by watch_channel.sh (standalone)
and worker/channel_watch.py (Celery-based), so the "how do I list a
channel's videos" logic exists in exactly one place.
"""
import argparse
import json
import re
import sys

KNOWN_TABS = ("streams", "videos", "shorts", "featured", "playlists", "community")


def normalize_to_streams_tab(channel_url):
    """Points the URL at the right 'past broadcasts' tab for the
    platform — not live-only, not Shorts/clips. Real bug fixed: this
    only ever handled YouTube URLs; a bare Twitch channel URL fell
    through unchanged, and yt-dlp's default behavior for that is its
    live-stream-only extractor — confirmed directly on a real channel:
    it reported "not currently live" instead of ever listing VODs,
    since Twitch has no "/streams" tab in the YouTube sense at all —
    its real VOD archive lives at /videos. If the URL already targets a
    specific tab, leave it alone (explicit choice wins)."""
    url = channel_url.rstrip("/")
    for tab in KNOWN_TABS:
        if url.endswith(f"/{tab}"):
            return url  # already targets a specific tab, don't override
    if re.search(r"youtube\.com/(@[\w.-]+|channel/[\w-]+|c/[\w.-]+)$", url):
        return url + "/streams"
    if re.search(r"twitch\.tv/[\w-]+$", url):
        return url + "/videos"  # Twitch's real VOD archive tab — /streams isn't a real distinct page here
    return url  # not a recognizable bare-channel URL — pass through as-is


def list_videos(channel_url, max_results=15, min_duration_sec=180):
    import yt_dlp
    url = normalize_to_streams_tab(channel_url)
    opts = {"quiet": True, "no_warnings": True, "extract_flat": True, "playlistend": max_results}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    entries = info.get("entries") or []
    out = []
    for e in entries:
        if not e.get("id"):
            continue
        # secondary safety net: flat-playlist extraction on the /streams
        # tab shouldn't surface Shorts at all, but if duration IS present
        # and clearly short-length, skip it rather than trust the tab
        # alone — duration is often absent in flat mode, so only filter
        # when we actually have the number, never exclude on a guess
        duration = e.get("duration")
        if duration is not None and duration < min_duration_sec:
            continue
        out.append({
            "id": e["id"],
            "url": e.get("url") or e.get("webpage_url"),
            "title": e.get("title", ""),
            "upload_date": e.get("upload_date", ""),  # YYYYMMDD or empty
            "duration": duration,
        })
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("channel_url")
    p.add_argument("--max", type=int, default=15)
    p.add_argument("--min-duration", type=int, default=180,
                    help="skip entries shorter than this (seconds) when duration is known — default 180s excludes Shorts-length clips")
    args = p.parse_args()

    try:
        videos = list_videos(args.channel_url, args.max, args.min_duration)
    except ImportError:
        print(json.dumps({"error": "yt-dlp not installed"}))
        sys.exit(1)
    except Exception as e:
        print(json.dumps({"error": str(e)[:500]}))
        sys.exit(1)

    print(json.dumps({"videos": videos}))


if __name__ == "__main__":
    main()
