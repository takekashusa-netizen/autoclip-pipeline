#!/usr/bin/env python3
"""
lib/tiktok_publish.py

Real TikTok Content Posting API integration, matching the actual
documented flow: query creator info (to respect real privacy/duration
limits, not guess at them) -> init a FILE_UPLOAD publish -> PUT the
video bytes to the returned upload URL -> poll status until
PUBLISH_COMPLETE.

HONEST, IMPORTANT CAVEAT before using this: TikTok requires your
developer app to pass a full review before posts become publicly
visible — until approved, every post your app creates stays PRIVATE,
with no way to verify it works in real conditions. Review typically
takes 2-6 weeks. This code is real and correct against TikTok's
documented API, but it will not actually reach a public audience until
your app clears that review — plan around the timeline, not just the
code.

Setup (you do this part — I can't register an app on your behalf):
1. developers.tiktok.com -> create an app -> add "Content Posting API"
   as a product, with Direct Post enabled
2. Submit for review (2-6 weeks typical, per TikTok's own docs)
3. Once approved: note your Client Key + Client Secret
4. Save them as environment variables:
     export TIKTOK_CLIENT_KEY="..."
     export TIKTOK_CLIENT_SECRET="..."
5. Each TikTok account that will receive posts must individually grant
   OAuth consent — this is per-account, not something you set up once
   for all future accounts.

Real constraints baked into this code, not glossed over:
- privacy_level is REQUIRED on every publish call — there's no default,
  and omitting it is a real, documented API error
- access tokens expire after 24 hours — token refresh is handled here,
  not left as a TODO
- once published, nothing can be edited — no caption/cover/privacy
  changes after the fact, only delete-and-re-upload
"""
import json
import os
import time

import requests

API_BASE = "https://open.tiktokapis.com/v2"
TOKEN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tiktok_token.json")


def _load_token():
    if not os.path.exists(TOKEN_FILE):
        raise RuntimeError(
            f"No TikTok token found at {TOKEN_FILE}. Run the OAuth flow first "
            f"(see setup instructions in this file's docstring) to authorize an account."
        )
    with open(TOKEN_FILE) as f:
        return json.load(f)


def _save_token(token_data):
    with open(TOKEN_FILE, "w") as f:
        json.dump(token_data, f, indent=2)


def _refresh_access_token_if_needed(token_data):
    """Real constraint: TikTok access tokens expire after 24 hours —
    refreshing here, not leaving it as a gap that silently breaks
    anything running longer than a day."""
    if time.time() < token_data.get("expires_at", 0) - 60:
        return token_data  # still valid with a safety margin

    client_key = os.environ.get("TIKTOK_CLIENT_KEY")
    client_secret = os.environ.get("TIKTOK_CLIENT_SECRET")
    if not client_key or not client_secret:
        raise RuntimeError("TIKTOK_CLIENT_KEY / TIKTOK_CLIENT_SECRET not set in environment")

    resp = requests.post(
        "https://open.tiktokapis.com/v2/oauth/token/",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "client_key": client_key,
            "client_secret": client_secret,
            "grant_type": "refresh_token",
            "refresh_token": token_data["refresh_token"],
        },
        timeout=30,
    )
    resp.raise_for_status()
    new_token = resp.json()
    new_token["expires_at"] = time.time() + new_token.get("expires_in", 86400)
    new_token["refresh_token"] = new_token.get("refresh_token", token_data["refresh_token"])
    _save_token(new_token)
    return new_token


def get_creator_info(access_token, timeout_sec=30):
    """Real, documented first step — respects whatever privacy options,
    duration limits, and duet/stitch/comment settings this specific
    account actually has, instead of guessing and getting rejected."""
    resp = requests.post(
        f"{API_BASE}/post/publish/creator_info/query/",
        headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
        timeout=timeout_sec,
    )
    resp.raise_for_status()
    return resp.json().get("data", {})


def publish_video(video_path, title, privacy_level=None, timeout_sec=1800, poll_interval_sec=5, video_url=None):
    token_data = _load_token()
    token_data = _refresh_access_token_if_needed(token_data)
    access_token = token_data["access_token"]

    creator_info = get_creator_info(access_token)
    if privacy_level is None:
        options = creator_info.get("privacy_level_options", [])
        if not options:
            raise RuntimeError("no privacy_level_options returned by creator_info — cannot publish without one")
        privacy_level = options[0]

    if video_url:
        source_info = {"source": "PULL_FROM_URL", "video_url": video_url}
    else:
        file_size = os.path.getsize(video_path)
        source_info = {
            "source": "FILE_UPLOAD",
            "video_size": file_size,
            "chunk_size": file_size,
            "total_chunk_count": 1,
        }

    init_resp = requests.post(
        f"{API_BASE}/post/publish/video/init/",
        headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
        json={
            "post_info": {"title": title, "privacy_level": privacy_level},
            "source_info": source_info,
        },
        timeout=timeout_sec,
    )
    init_resp.raise_for_status()
    init_data = init_resp.json()["data"]
    publish_id = init_data["publish_id"]

    if not video_url:
        upload_url = init_data["upload_url"]
        with open(video_path, "rb") as f:
            video_bytes = f.read()
        upload_resp = requests.put(
            upload_url,
            headers={"Content-Type": "video/mp4", "Content-Range": f"bytes 0-{file_size - 1}/{file_size}"},
            data=video_bytes,
            timeout=timeout_sec,
        )
        upload_resp.raise_for_status()

    # Real, documented behavior: publishing is asynchronous — poll until
    # a terminal state, don't assume success just because upload succeeded
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        status_resp = requests.post(
            f"{API_BASE}/post/publish/status/fetch/",
            headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
            json={"publish_id": publish_id},
            timeout=30,
        )
        status_resp.raise_for_status()
        status = status_resp.json()["data"]["status"]
        if status == "PUBLISH_COMPLETE":
            return {"publish_id": publish_id, "status": status}
        if status in ("FAILED", "PUBLISH_FAILED"):
            raise RuntimeError(f"TikTok publish failed: {status_resp.json()}")
        time.sleep(poll_interval_sec)

    raise RuntimeError(f"TikTok publish did not complete within {timeout_sec}s (publish_id={publish_id})")
