#!/usr/bin/env python3
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COOKIE_BROWSER = os.environ.get("PIPELINE_COOKIE_BROWSER", "chrome")


def main():
    job, url = sys.argv[1], sys.argv[2]
    try:
        import yt_dlp
    except ImportError:
        print(json.dumps({"error": "yt-dlp not installed"}))
        sys.exit(1)

    raw_dir = os.path.join(ROOT, "projects", job, "raw")
    os.makedirs(raw_dir, exist_ok=True)
    out_template = os.path.join(raw_dir, "source.%(ext)s")

    ydl_opts = {
        "outtmpl": out_template,
        "format": "bv*[height<=1080]+140/bv*[height<=1080]+ba/b[height<=1080]/b",
        "merge_output_format": "mp4",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "cookiesfrombrowser": (COOKIE_BROWSER,),
        "remote_components": ["ejs:github"],
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(url, download=True)
        except yt_dlp.utils.DownloadError as e:
            msg = str(e)
            if "Unsupported URL" in msg:
                print(json.dumps({"error": "unsupported site/URL"}))
            elif "Sign in" in msg or "login" in msg.lower() or "cookies" in msg.lower():
                print(json.dumps({"error": "needs login/cookies"}))
            elif "Private video" in msg or "unavailable" in msg.lower():
                print(json.dumps({"error": "video is private or unavailable"}))
            else:
                print(json.dumps({"error": msg[:500]}))
            sys.exit(1)
        downloaded = ydl.prepare_filename(info)
        if info.get("requested_downloads"):
            downloaded = info["requested_downloads"][0].get("filepath", downloaded)

    final_path = os.path.join(raw_dir, "source.mp4")
    if os.path.abspath(downloaded) != os.path.abspath(final_path):
        os.replace(downloaded, final_path)

    print(json.dumps({
        "path": final_path,
        "title": info.get("title", ""),
        "duration_sec": info.get("duration"),
        "was_live": bool(info.get("is_live") or info.get("was_live")),
    }))


if __name__ == "__main__":
    main()
