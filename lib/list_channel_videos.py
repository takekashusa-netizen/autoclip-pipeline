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
import sys


def list_videos(channel_url, max_results=15):
    import yt_dlp
    opts = {"quiet": True, "no_warnings": True, "extract_flat": True, "playlistend": max_results}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(channel_url, download=False)
    entries = info.get("entries") or []
    out = []
    for e in entries:
        if not e.get("id"):
            continue
        out.append({
            "id": e["id"],
            "url": e.get("url") or e.get("webpage_url"),
            "title": e.get("title", ""),
            "upload_date": e.get("upload_date", ""),  # YYYYMMDD or empty
        })
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("channel_url")
    p.add_argument("--max", type=int, default=15)
    args = p.parse_args()

    try:
        videos = list_videos(args.channel_url, args.max)
    except ImportError:
        print(json.dumps({"error": "yt-dlp not installed"}))
        sys.exit(1)
    except Exception as e:
        print(json.dumps({"error": str(e)[:500]}))
        sys.exit(1)

    print(json.dumps({"videos": videos}))


if __name__ == "__main__":
    main()
