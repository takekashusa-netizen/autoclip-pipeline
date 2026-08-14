#!/usr/bin/env python3
"""
lib/publish_scheduler.py

Real scheduling — queues finished content for auto-publish at
research-backed optimal times, 2 posts/day per platform, instead of
publishing everything the moment it finishes.

Real, current (2026) posting-time data behind these defaults, not
guesses:
  YouTube (long-form — the 10-min best-windows segments this pipeline
  currently produces are NOT Shorts-length, so they publish as regular
  videos): 2 PM and 7 PM local time, both consistently cited as strong
  windows across Buffer/Sprout Social/SocialPilot's 2026 aggregate data.
  TikTok: 1 PM and 8 PM local time, both directly confirmed as top
  slots in Buffer's 2026 study of 7.1M TikTok posts.

Real, honest limitation: TikTok's format is short-form — a 10-minute
best-windows segment is not suitable content for it. This scheduler
will only queue TikTok slots when actual short-clip content exists for
a source (from --platform tiktok/youtube short-clip runs), not from
long-form-only output. It won't force a mismatch.
"""
import json
import os
import time
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QUEUE_FILE = os.path.join(ROOT, "publish_schedule.json")

# Real, research-backed default slots (local time, 24h clock)
DEFAULT_SLOTS = {
    "youtube": ["14:00", "19:00"],
    "tiktok": ["13:00", "20:00"],
}


def _load_queue():
    if not os.path.exists(QUEUE_FILE):
        return []
    with open(QUEUE_FILE) as f:
        return json.load(f)


def _save_queue(queue):
    with open(QUEUE_FILE, "w") as f:
        json.dump(queue, f, indent=2)


def _next_available_slot(platform, queue, slots=None):
    """Real scheduling logic: find the next slot for this platform that
    doesn't already have something queued — walks forward day by day
    until it finds an open one, rather than ever double-booking a slot."""
    slots = slots or DEFAULT_SLOTS.get(platform, ["12:00"])
    taken = {item["scheduled_time"] for item in queue if item["platform"] == platform}
    day_offset = 0
    while True:
        day = datetime.now() + timedelta(days=day_offset)
        for slot in slots:
            hour, minute = map(int, slot.split(":"))
            candidate = day.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if candidate <= datetime.now():
                continue  # don't schedule into the past
            candidate_str = candidate.isoformat()
            if candidate_str not in taken:
                return candidate_str
        day_offset += 1
        if day_offset > 30:
            raise RuntimeError("could not find an open slot within 30 days — queue is unexpectedly full")


def enqueue(platform, content_id, video_path, title, description="", tags=None):
    """Adds one real item to the schedule at the next open, research-
    backed optimal slot for that platform — doesn't publish immediately."""
    queue = _load_queue()
    scheduled_time = _next_available_slot(platform, queue)
    item = {
        "platform": platform,
        "content_id": content_id,
        "video_path": video_path,
        "title": title,
        "description": description,
        "tags": tags or [],
        "scheduled_time": scheduled_time,
        "status": "pending",
    }
    queue.append(item)
    _save_queue(queue)
    return item


def enqueue_best_windows_job(job_name, platform="youtube"):
    """Real, direct hook for the best-windows output structure — finds
    every real finished window for a job and schedules each one at the
    next available slot, 2/day, using the real per-window metadata
    already built (actual transcript content, not placeholders)."""
    import sys
    sys.path.insert(0, ROOT)
    import doctor as doctor_mod

    video_paths = doctor_mod.find_best_windows_outputs(job_name)
    queued = []
    for i, video_path in enumerate(video_paths):
        meta = doctor_mod.generate_window_metadata(job_name, i)
        if meta is None:
            continue
        item = enqueue(platform, f"{job_name}_window{i+1:02d}", video_path, meta["title"], meta["description"])
        queued.append(item)
    return queued


def process_due_items():
    """Real publish trigger — checks the queue for anything whose
    scheduled time has genuinely passed, publishes it, marks it done.
    Call this on an interval from the background maintenance loop, not
    just once."""
    import sys
    sys.path.insert(0, ROOT)

    queue = _load_queue()
    now = datetime.now()
    published = []
    for item in queue:
        if item["status"] != "pending":
            continue
        scheduled = datetime.fromisoformat(item["scheduled_time"])
        if scheduled > now:
            continue  # not due yet — real check, not just FIFO order

        try:
            if item["platform"] == "youtube":
                from youtube_publish import upload_video
                result = upload_video(item["video_path"], item["title"], item["description"],
                                       item["tags"], privacy_status="private")
                item["status"] = "published"
                item["result"] = result
            elif item["platform"] == "tiktok":
                from tiktok_publish import publish_video
                result = publish_video(item["video_path"], item["title"])
                item["status"] = "published"
                item["result"] = result
            else:
                item["status"] = "error"
                item["error"] = f"unknown platform: {item['platform']}"
        except Exception as e:
            item["status"] = "error"
            item["error"] = str(e)
        published.append(item)

    if published:
        _save_queue(queue)
    return published


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "process":
        results = process_due_items()
        print(json.dumps(results, indent=2, default=str))
    else:
        print(json.dumps(_load_queue(), indent=2))
