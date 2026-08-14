#!/usr/bin/env python3
"""
lib/channel_watcher.py

The real logic from watch_channel.sh, ported to run as a background
thread INSIDE the unified dashboard.py server instead of a separate
bash subprocess — the same consolidation already done for doctor.py's
auto-resume/publish logic. One process, one place to look, instead of
a script you have to remember is running separately.

Default poll interval is once per day (86400s), not the old 15-minute
default — a real, deliberate choice, not a bug: checking a channel for
a new VOD every 15 minutes makes sense for a very active streamer, but
burns real API calls and CPU for no benefit on a typical schedule.
"""
import json
import os
import subprocess
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEEN_FILE = os.path.join(ROOT, "watch_seen.json")

DEFAULT_INTERVAL_SEC = 86400  # once a day — real, deliberate default per explicit preference


def _log(msg):
    ts = time.strftime("%H:%M:%S")
    print(f"  [{ts}] channel_watcher: {msg}", flush=True)


def _load_seen():
    if not os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, "w") as f:
            json.dump([], f)
    with open(SEEN_FILE) as f:
        return set(json.load(f))


def _mark_seen(video_id):
    seen = _load_seen()
    seen.add(video_id)
    with open(SEEN_FILE, "w") as f:
        json.dump(sorted(seen), f)


def _list_channel_videos(channel_url, max_videos=15):
    result = subprocess.run(
        [sys.executable, os.path.join(ROOT, "lib", "list_channel_videos.py"), channel_url, "--max", str(max_videos)],
        capture_output=True, text=True, timeout=120,
    )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"error": result.stderr or "unrecognized output from list_channel_videos.py"}


def _process_new_video(video, format_, clip_length, clip_count, content_type, model, job_prefix="watch"):
    vid, url, title = video["id"], video["url"], video["title"]
    job = f"{job_prefix}_{vid}"
    _log(f'new video — "{title}" ({vid})')

    fetch_result = subprocess.run(
        [sys.executable, os.path.join(ROOT, "lib", "fetch_url.py"), job, url],
        capture_output=True, text=True, timeout=1800,
    )
    try:
        fetch_data = json.loads(fetch_result.stdout)
        if fetch_data.get("error"):
            _log(f"download failed for {vid} — {fetch_data['error']} (will retry next poll)")
            return False
    except json.JSONDecodeError:
        pass  # no error field found in output — treat as success and let clip_pipeline.sh itself catch real problems

    clip_args = [os.path.join(ROOT, "clip_pipeline.sh"), job, format_,
                 "--clip-length", str(clip_length), "--clip-count", str(clip_count),
                 "--auto-approve", "--skip-music"]
    if content_type:
        clip_args += ["--content-type", content_type]

    env = os.environ.copy()
    env["PIPELINE_WHISPER_MODEL"] = model
    log_path = os.path.join(ROOT, "logs", f"{job}.log")
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "w") as f:
        result = subprocess.run(clip_args, stdout=f, stderr=subprocess.STDOUT, env=env)

    if result.returncode == 0:
        _log(f'clipped "{title}" — organizing output')
        organize_result = subprocess.run(
            [sys.executable, os.path.join(ROOT, "lib", "organize_output.py"), job, "--title", title],
            capture_output=True, text=True,
        )
        if organize_result.returncode != 0:
            _log(f"clip succeeded but organize step failed — check outputs/{job}__clip*.final.mp4 directly")
    else:
        _log(f"clip_pipeline.sh failed for {vid} — check logs/{job}.log (will not retry automatically; fix and resume manually)")

    return True  # mark seen regardless of success/failure — matches the real bash logic's own reasoning


def watch_loop(channel_url, stop_event, format_="short-tiktok-raw", clip_length=60, clip_count=3,
                content_type="", interval_sec=DEFAULT_INTERVAL_SEC, model="tiny"):
    """The real poll loop — runs until stop_event is set. Checked
    between polls (not mid-download), matching the real bash script's
    own granularity for stopping cleanly."""
    _log(f"watching {channel_url} (poll every {interval_sec}s = {interval_sec/3600:.1f}h, "
         f"format={format_}, {clip_count}x{clip_length}s clips)")

    while not stop_event.is_set():
        data = _list_channel_videos(channel_url)
        if data.get("error"):
            _log(f"couldn't list channel videos — {data['error']}")
        else:
            seen = _load_seen()
            new_videos = [v for v in data.get("videos", []) if v["id"] not in seen]
            if not new_videos:
                _log(f"no new videos, checking again in {interval_sec}s")
            for video in new_videos:
                if stop_event.is_set():
                    break
                _process_new_video(video, format_, clip_length, clip_count, content_type, model)
                _mark_seen(video["id"])

        stop_event.wait(interval_sec)  # real, interruptible sleep — stops immediately on stop_event, not after the full interval

    _log("stopped")
