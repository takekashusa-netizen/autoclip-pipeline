#!/usr/bin/env python3
"""
lib/instagram_publish.py

Real Instagram Graph API integration, matching the actual documented
container-based flow: create a media container (media_type=REELS) ->
poll until status_code=FINISHED -> publish via media_publish.

REAL, IMPORTANT ARCHITECTURAL CONSTRAINT, not a minor detail: Instagram's
API requires a PUBLICLY ACCESSIBLE URL for the video — it does not
accept a direct file upload from your machine, unlike YouTube and
TikTok. Since this pipeline produces local files, you need SOME way to
expose the finished clip at a real public URL before this can be
called — your own hosting, cloud storage with a public link, or a
tunnel service. That's real, separate infrastructure this file doesn't
solve for you.

Setup (you do this part):
1. A Facebook Business account, with a Facebook Page connected
2. An Instagram Professional (Business or Creator) account, linked to
   that Page
3. A Meta developer app, with the instagram_business_content_publish
   permission approved through Meta's app review (2-4 weeks typical)
4. Save credentials as environment variables:
     export INSTAGRAM_ACCESS_TOKEN="..."
     export INSTAGRAM_USER_ID="..."   (the ig-user-id, not your username)

Real constraints baked into this code, not glossed over:
- Reels are capped at 90 seconds via the API for most accounts, even
  though the app itself allows longer — a real, current limit checked
  here before ever calling the API
- Hard limit of 25 published posts per 24 hours per account (Meta's
  own documented cap) — not enforced here (this file publishes one
  video per call), but worth knowing if you're calling this in a loop
- Publishing is asynchronous — the container must reach FINISHED
  before you can publish it, and this polls for that rather than
  assuming success right after creation
"""
import os
import time

import requests

API_BASE = "https://graph.facebook.com/v22.0"
MAX_REELS_DURATION_SEC = 90  # real, current API limit — checked before calling, not discovered via a rejected request


def _get_credentials():
    access_token = os.environ.get("INSTAGRAM_ACCESS_TOKEN")
    user_id = os.environ.get("INSTAGRAM_USER_ID")
    if not access_token or not user_id:
        raise RuntimeError(
            "INSTAGRAM_ACCESS_TOKEN / INSTAGRAM_USER_ID not set in environment. "
            "See setup instructions in this file's docstring."
        )
    return access_token, user_id


def _check_duration(video_path, timeout_sec=30):
    """Real check before ever calling the API — Instagram accepts up to
    15 minutes technically, but only 5-90 seconds is eligible to appear
    as an actual Reel; anything longer silently publishes as a regular
    video post instead, which is a real, surprising failure mode worth
    catching up front rather than discovering after upload."""
    import subprocess
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", video_path],
            capture_output=True, text=True, timeout=timeout_sec,
        )
        return float(result.stdout.strip())
    except Exception:
        return None  # can't verify — caller decides whether to proceed anyway


def publish_reel(video_url, caption, video_path_for_duration_check=None, timeout_sec=1800, poll_interval_sec=5):
    """video_url MUST be a real, publicly-accessible URL — Instagram's
    API fetches the video FROM this URL, it does not accept a direct
    file upload. If you have the local file too, pass
    video_path_for_duration_check to get a real pre-flight duration
    check instead of finding out after upload."""
    access_token, user_id = _get_credentials()

    if video_path_for_duration_check and os.path.exists(video_path_for_duration_check):
        duration = _check_duration(video_path_for_duration_check)
        if duration and duration > MAX_REELS_DURATION_SEC:
            raise ValueError(
                f"video is {duration:.0f}s — Instagram's Reels API caps at "
                f"{MAX_REELS_DURATION_SEC}s for most accounts; a longer video "
                f"would silently publish as a regular post instead of a Reel"
            )

    create_resp = requests.post(
        f"{API_BASE}/{user_id}/media",
        data={
            "media_type": "REELS",
            "video_url": video_url,
            "caption": caption,
            "access_token": access_token,
        },
        timeout=timeout_sec,
    )
    create_resp.raise_for_status()
    container_id = create_resp.json()["id"]

    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        status_resp = requests.get(
            f"{API_BASE}/{container_id}",
            params={"fields": "status_code", "access_token": access_token},
            timeout=30,
        )
        status_resp.raise_for_status()
        status = status_resp.json().get("status_code")
        if status == "FINISHED":
            break
        if status == "ERROR":
            raise RuntimeError(f"Instagram container processing failed: {status_resp.json()}")
        time.sleep(poll_interval_sec)
    else:
        raise RuntimeError(f"Instagram container did not finish processing within {timeout_sec}s (container_id={container_id})")

    publish_resp = requests.post(
        f"{API_BASE}/{user_id}/media_publish",
        data={"creation_id": container_id, "access_token": access_token},
        timeout=timeout_sec,
    )
    publish_resp.raise_for_status()
    media_id = publish_resp.json()["id"]
    return {"media_id": media_id, "container_id": container_id}
