import json
import os
import subprocess
import sys

from worker.celery_app import app

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEEN_PATH = os.path.join(ROOT, "worker", ".channel_watch_seen.json")

CHANNEL_URL = os.environ.get("PIPELINE_WATCH_CHANNEL_URL", "")
WATCH_FORMAT = os.environ.get("PIPELINE_WATCH_FORMAT", "short-tiktok-raw")
WATCH_CONTENT_TYPE = os.environ.get("PIPELINE_WATCH_CONTENT_TYPE", "")
WATCH_CLIP_LENGTH = int(os.environ.get("PIPELINE_WATCH_CLIP_LENGTH", 60))
WATCH_CLIP_COUNT = int(os.environ.get("PIPELINE_WATCH_CLIP_COUNT", 3))
WATCH_MAX_NEW = int(os.environ.get("PIPELINE_WATCH_MAX_NEW", 3))  # cap per poll — don't queue a channel backlog at once


def _load_seen():
    if os.path.exists(SEEN_PATH):
        return set(json.load(open(SEEN_PATH)))
    return set()


def _save_seen(seen):
    json.dump(sorted(seen), open(SEEN_PATH, "w"))


def _list_channel_videos(channel_url):
    """Flat playlist extraction — just IDs/titles, no per-video download."""
    import yt_dlp
    opts = {"quiet": True, "no_warnings": True, "extract_flat": True, "playlistend": 15}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(channel_url, download=False)
    entries = info.get("entries") or []
    return [{"id": e.get("id"), "url": e.get("url") or e.get("webpage_url"),
             "title": e.get("title", "")} for e in entries if e.get("id")]


@app.task(name="pipeline.channel_watch")
def channel_watch():
    if not CHANNEL_URL:
        return {"skipped": "PIPELINE_WATCH_CHANNEL_URL not set"}

    seen = _load_seen()
    try:
        videos = _list_channel_videos(CHANNEL_URL)
    except ImportError:
        return {"error": "yt-dlp not installed"}
    except Exception as e:
        return {"error": str(e)}

    new_videos = [v for v in videos if v["id"] not in seen][:WATCH_MAX_NEW]
    queued = []

    for v in new_videos:
        job = f"watch_{v['id']}"
        args = [
            os.path.join(ROOT, "clip_pipeline.sh"), job, WATCH_FORMAT,
            "--clip-length", str(WATCH_CLIP_LENGTH),
            "--clip-count", str(WATCH_CLIP_COUNT),
        ]
        if WATCH_CONTENT_TYPE:
            args += ["--content-type", WATCH_CONTENT_TYPE]

        # download first (separate step so a download failure doesn't burn
        # a clip_pipeline run against an empty raw dir)
        fetch = subprocess.run(
            [sys.executable, os.path.join(ROOT, "lib", "fetch_url.py"), job, v["url"]],
            cwd=ROOT, capture_output=True, text=True,
        )
        if fetch.returncode != 0:
            continue

        subprocess.Popen(args, cwd=ROOT, start_new_session=True)  # real fix: fire-and-forget, long-running, and now genuinely detached from this worker process
        queued.append({"job": job, "title": v["title"]})
        seen.add(v["id"])

    _save_seen(seen)
    return {"queued": queued, "checked": len(videos)}


app.conf.beat_schedule = dict(app.conf.beat_schedule or {})
app.conf.beat_schedule["channel-watch"] = {
    "task": "pipeline.channel_watch",
    "schedule": int(os.environ.get("PIPELINE_WATCH_INTERVAL_SECONDS", 15 * 60)),
}
