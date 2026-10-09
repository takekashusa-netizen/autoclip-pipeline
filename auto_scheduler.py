#!/usr/bin/env python3
"""
auto_scheduler.py

Real, automated social media posting scheduler for TakeKash/GtaxZombies.
Runs every 30 minutes via launchd. Checks publish_schedule.json for entries
due to post, publishes to each platform, and updates status.

Platforms:
  - YouTube: changes private videos to public at scheduled time (WORKING)
  - TikTok:  posts when API audit clears (code ready, API pending)
  - Instagram: posts when OAuth is connected (code ready, auth pending)

Run manually:   python3 auto_scheduler.py
Run once-only:  python3 auto_scheduler.py --once
Check status:   python3 auto_scheduler.py --status
Add YT clips:   python3 auto_scheduler.py --add-youtube-clips
"""
import argparse
import json
import os
import sys
import time
import sqlite3
import pickle
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.abspath(__file__))
QUEUE_PATH = os.path.join(ROOT, "publish_schedule.json")
DB_PATH = os.path.join(ROOT, "takekash.db")
LOG_PATH = os.path.join(ROOT, "logs", "scheduler.log")

sys.path.insert(0, os.path.join(ROOT, "lib"))


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] scheduler: {msg}"
    print(line, flush=True)
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    with open(LOG_PATH, "a") as f:
        f.write(line + "\n")


def load_queue():
    if not os.path.exists(QUEUE_PATH):
        return []
    with open(QUEUE_PATH) as f:
        return json.load(f)


def save_queue(queue):
    with open(QUEUE_PATH, "w") as f:
        json.dump(queue, f, indent=2)


def get_youtube_service():
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    token_path = os.path.join(ROOT, "youtube_token.pickle")
    if not os.path.exists(token_path):
        return None
    with open(token_path, "rb") as f:
        creds = pickle.load(f)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return build("youtube", "v3", credentials=creds)


def publish_youtube(video_id, title=""):
    """Change a private YouTube video to public."""
    try:
        youtube = get_youtube_service()
        if not youtube:
            return False, "no YouTube credentials"
        youtube.videos().update(
            part="status",
            body={"id": video_id, "status": {"privacyStatus": "public"}}
        ).execute()
        return True, "published to YouTube"
    except Exception as e:
        return False, str(e)


def publish_tiktok(video_path, title, description, tags):
    """Post to TikTok — requires OAuth token (pending audit approval)."""
    token_path = os.path.join(ROOT, "tiktok_token.json")
    if not os.path.exists(token_path):
        return False, "TikTok OAuth not connected — pending audit approval"
    try:
        from tiktok_publish import publish_video
        publish_video(video_path, title)
        return True, "published to TikTok"
    except Exception as e:
        return False, str(e)


def publish_instagram(video_path, title, description):
    """Post to Instagram — requires OAuth token (not yet connected)."""
    ig_token = os.environ.get("INSTAGRAM_ACCESS_TOKEN")
    ig_user = os.environ.get("INSTAGRAM_USER_ID")
    if not ig_token or not ig_user:
        return False, "Instagram not connected — add INSTAGRAM_ACCESS_TOKEN and INSTAGRAM_USER_ID to .zshrc"
    try:
        import urllib.request
        # Instagram Graph API video publish flow
        # Step 1: create media container
        container_url = f"https://graph.facebook.com/v18.0/{ig_user}/media"
        data = json.dumps({
            "media_type": "REELS",
            "video_url": video_path,  # needs public URL
            "caption": f"{title}\n\n{description}",
            "access_token": ig_token
        }).encode()
        req = urllib.request.Request(container_url, data=data,
                                      headers={"Content-Type": "application/json"})
        resp = json.loads(urllib.request.urlopen(req).read())
        creation_id = resp.get("id")
        if not creation_id:
            return False, f"no creation_id: {resp}"
        # Step 2: publish
        publish_url = f"https://graph.facebook.com/v18.0/{ig_user}/media_publish"
        pub_data = json.dumps({
            "creation_id": creation_id,
            "access_token": ig_token
        }).encode()
        pub_req = urllib.request.Request(publish_url, data=pub_data,
                                          headers={"Content-Type": "application/json"})
        pub_resp = json.loads(urllib.request.urlopen(pub_req).read())
        return True, f"published to Instagram: {pub_resp.get('id','')}"
    except Exception as e:
        return False, str(e)


def add_youtube_clips_to_queue(days_apart=1, start_hour=14):
    """
    Add the 14 private Apex YouTube clips to the queue with staggered
    publish times — one per day at a consistent time.
    """
    youtube = get_youtube_service()
    if not youtube:
        log("cannot add YouTube clips — no credentials")
        return

    # fetch all private Apex clips
    channels = youtube.channels().list(part="contentDetails", mine=True).execute()
    uploads_id = channels["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]

    all_items = []
    token = None
    while True:
        resp = youtube.playlistItems().list(
            part="snippet", playlistId=uploads_id,
            maxResults=50, pageToken=token
        ).execute()
        all_items += resp["items"]
        token = resp.get("nextPageToken")
        if not token:
            break

    # get privacy status
    vid_ids = [i["snippet"]["resourceId"]["videoId"] for i in all_items]
    private_apex = []
    KEYWORDS = ["CLUTCH","ROAD","CHILLY","SMELL","COME","SQUADS","SMOOTH",
                "SHOULDN","ALRIGHT","CHAMPIONS","RING","1V3","GRIND",
                "STANDOFF","GAS","MESSED","POWER"]
    for i in range(0, len(vid_ids), 50):
        batch = vid_ids[i:i+50]
        resp = youtube.videos().list(part="snippet,status", id=",".join(batch)).execute()
        for item in resp["items"]:
            if (item["status"]["privacyStatus"] == "private" and
                any(k in item["snippet"]["title"].upper() for k in KEYWORDS)):
                private_apex.append((item["id"], item["snippet"]["title"]))

    log(f"found {len(private_apex)} private Apex clips to schedule")

    queue = load_queue()
    existing_ids = {i.get("youtube_video_id") for i in queue}

    start_date = datetime.now().replace(hour=start_hour, minute=0, second=0, microsecond=0)
    if start_date < datetime.now():
        start_date += timedelta(days=1)

    added = 0
    for idx, (vid_id, title) in enumerate(sorted(private_apex, key=lambda x: x[1])):
        if vid_id in existing_ids:
            continue
        scheduled = start_date + timedelta(days=idx * days_apart)
        queue.append({
            "platform": "youtube",
            "content_id": f"apex_yt_{vid_id}",
            "youtube_video_id": vid_id,
            "title": title,
            "scheduled_time": scheduled.isoformat(),
            "status": "approved",
            "video_path": "",
        })
        log(f"  queued: {title[:55]} → {scheduled.strftime('%Y-%m-%d %H:%M')}")
        added += 1

    save_queue(queue)
    log(f"added {added} YouTube clips to schedule")


def run_scheduler():
    """Main scheduling loop — check queue and post anything due."""
    queue = load_queue()
    now = datetime.now()
    changed = False

    for entry in queue:
        if entry.get("status") not in ("approved", "pending"):
            continue

        scheduled_str = entry.get("scheduled_time", "")
        if not scheduled_str:
            continue

        try:
            scheduled = datetime.fromisoformat(scheduled_str)
        except ValueError:
            continue

        if scheduled > now:
            continue  # not due yet

        platform = entry.get("platform", "")
        content_id = entry.get("content_id", "")
        title = entry.get("title", "")
        video_path = entry.get("video_path", "")
        description = entry.get("description", "")
        tags = entry.get("tags", [])

        log(f"posting: [{platform}] {content_id[:45]}")

        if platform == "youtube":
            vid_id = entry.get("youtube_video_id", "")
            success, msg = publish_youtube(vid_id, title) if vid_id else (False, "no video_id")

        elif platform == "tiktok":
            if not video_path or not os.path.exists(video_path):
                entry["status"] = "failed"
                entry["error_message"] = "video file not found"
                log(f"  FAILED: video not found at {video_path}")
                changed = True
                continue
            success, msg = publish_tiktok(video_path, title, description, tags)

        elif platform == "instagram":
            if not video_path or not os.path.exists(video_path):
                entry["status"] = "failed"
                entry["error_message"] = "video file not found"
                log(f"  FAILED: video not found at {video_path}")
                changed = True
                continue
            success, msg = publish_instagram(video_path, title, description)

        else:
            log(f"  unknown platform: {platform} — skipping")
            continue

        if success:
            entry["status"] = "published"
            entry["published_at"] = now.isoformat()
            log(f"  ✓ {msg}")
        elif "not connected" in msg.lower() or "pending" in msg.lower() or "oauth" in msg.lower():
            log(f"  ⏸ skipped (platform not connected yet): {msg}")
        else:
            entry["status"] = "failed"
            entry["error_message"] = msg
            log(f"  ✗ {msg}")

        changed = True

    if changed:
        save_queue(queue)

    due_count = sum(1 for i in queue if i.get("status") in ("approved","pending"))
    log(f"run complete — {due_count} entries still pending/approved")
    return changed


def print_status():
    """Print a human-readable schedule."""
    queue = load_queue()
    now = datetime.now()

    by_platform = {}
    for i in queue:
        p = i.get("platform","?")
        if p not in by_platform:
            by_platform[p] = []
        by_platform[p].append(i)

    print(f"\n{'='*60}")
    print(f"TakeKash Auto-Scheduler Status — {now.strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}")

    for platform, entries in sorted(by_platform.items()):
        print(f"\n{platform.upper()} ({len(entries)} entries)")
        print(f"{'─'*50}")
        for e in sorted(entries, key=lambda x: x.get("scheduled_time","")):
            sched = e.get("scheduled_time","?")[:16]
            status = e.get("status","?")
            title = e.get("title","")[:45]
            past = "⏰ DUE" if sched < now.strftime("%Y-%m-%dT%H:%M") else "📅"
            icon = "✅" if status == "published" else ("❌" if status == "failed" else past)
            print(f"  {icon} {sched} | {status:10} | {title}")

    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="TakeKash Auto-Scheduler")
    parser.add_argument("--once", action="store_true", help="Run once and exit")
    parser.add_argument("--status", action="store_true", help="Print schedule status")
    parser.add_argument("--add-youtube-clips", action="store_true",
                        help="Add private Apex YouTube clips to schedule")
    parser.add_argument("--days-apart", type=int, default=1,
                        help="Days between YouTube posts (default: 1)")
    parser.add_argument("--post-hour", type=int, default=14,
                        help="Hour to post YouTube clips (default: 14 = 2pm)")
    args = parser.parse_args()

    if args.status:
        print_status()
        sys.exit(0)

    if args.add_youtube_clips:
        add_youtube_clips_to_queue(args.days_apart, args.post_hour)
        print_status()
        sys.exit(0)

    log("auto_scheduler starting")
    run_scheduler()
    log("auto_scheduler done")
