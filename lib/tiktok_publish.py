#!/usr/bin/env python3
"""
lib/tiktok_publish.py

Posts a local video straight to TikTok through TikTok's own Content Posting
API. No third-party scheduler, no public URL, no Google Drive: the file is
uploaded from this Mac in chunks (FILE_UPLOAD).

Two delivery modes (TikTok's rules, not ours):

  direct  - /v2/post/publish/video/init/  (scope video.publish)
            Goes live on its own. Until the TikTok app passes TikTok's
            Direct Post audit, TikTok only allows this into a PRIVATE
            account / SELF_ONLY visibility.
  inbox   - /v2/post/publish/inbox/video/init/  (scope video.upload)
            Lands in the TikTok app's inbox as a draft; you tap Post.
            Works before the audit. TikTok's inbox API takes no caption,
            so the caption is returned for you to paste.

TIKTOK_POST_MODE env var: "auto" (default), "direct", or "inbox".
  auto = try direct PUBLIC_TO_EVERYONE; if TikTok answers that this app is
         unaudited, send the same video to the inbox instead. Never silently
         downgrades to a private post.

Chunk rules implemented per TikTok's Media Transfer Guide:
  - file < 5 MB: one chunk, chunk_size = whole file
  - otherwise chunk_size 10 MB (allowed 5-64 MB),
    total_chunk_count = floor(size / chunk_size), the last chunk carries the
    remainder (allowed up to 128 MB), chunks sent in order with
    Content-Range: bytes {first}-{last}/{total}
  - max 1000 chunks, 4 GB per video

Setup (only the account owner can do these):
  1. developers.tiktok.com -> your app -> add Login Kit + Content Posting API,
     enable Direct Post, request scopes user.info.basic, video.upload,
     video.publish, redirect URI https://takekash.com/oauth-callback
  2. put TIKTOK_CLIENT_KEY / TIKTOK_CLIENT_SECRET in .env (gitignored)
  3. python3 lib/tiktok_oauth_flow.py   -> writes tiktok_token.json
  4. submit the app for the Direct Post audit; until it passes, auto mode
     uses the inbox.
"""
import json
import os
import subprocess
import time

import requests

API_BASE = "https://open.tiktokapis.com/v2"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOKEN_FILE = os.path.join(ROOT, "tiktok_token.json")

MB = 1024 * 1024
MIN_CHUNK = 5 * MB
DEFAULT_CHUNK = 10 * MB
MAX_CHUNK = 64 * MB
MAX_LAST_CHUNK = 128 * MB
MAX_CHUNKS = 1000
MAX_VIDEO_BYTES = 4 * 1024 * MB
CAPTION_LIMIT = 2200


class TikTokError(RuntimeError):
    def __init__(self, message, code=None, payload=None):
        super().__init__(message)
        self.code = code
        self.payload = payload


# ---------------------------------------------------------------- env/token
def _load_env():
    """Reads KEY=VALUE lines from ROOT/.env without overriding real env vars."""
    path = os.path.join(ROOT, ".env")
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip().removeprefix("export ").strip(),
                                  v.strip().strip('"').strip("'"))


def _load_token():
    if not os.path.exists(TOKEN_FILE):
        raise TikTokError(f"No TikTok token at {TOKEN_FILE}. Run: python3 lib/tiktok_oauth_flow.py",
                          code="no_token")
    with open(TOKEN_FILE) as f:
        return json.load(f)


def _save_token(token_data):
    tmp = TOKEN_FILE + ".partial"
    with open(tmp, "w") as f:
        json.dump(token_data, f, indent=2)
    os.replace(tmp, TOKEN_FILE)


def get_access_token():
    """Access tokens last 24h; refreshed here with a 60s margin."""
    _load_env()
    token_data = _load_token()
    if time.time() < token_data.get("expires_at", 0) - 60:
        return token_data["access_token"]

    client_key = os.environ.get("TIKTOK_CLIENT_KEY")
    client_secret = os.environ.get("TIKTOK_CLIENT_SECRET")
    if not client_key or not client_secret:
        raise TikTokError("TIKTOK_CLIENT_KEY / TIKTOK_CLIENT_SECRET not set (.env)", code="no_client_keys")

    resp = requests.post(
        f"{API_BASE}/oauth/token/",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={"client_key": client_key, "client_secret": client_secret,
              "grant_type": "refresh_token", "refresh_token": token_data["refresh_token"]},
        timeout=30,
    )
    body = resp.json() if resp.content else {}
    if resp.status_code != 200 or "access_token" not in body:
        raise TikTokError(f"token refresh failed ({resp.status_code}): {body}. "
                          "If the refresh token expired, rerun lib/tiktok_oauth_flow.py",
                          code="refresh_failed", payload=body)
    body["expires_at"] = time.time() + body.get("expires_in", 86400)
    body.setdefault("refresh_token", token_data["refresh_token"])
    _save_token(body)
    return body["access_token"]


# --------------------------------------------------------------- api helper
def _api(path, access_token, payload=None, timeout=60):
    resp = requests.post(
        f"{API_BASE}{path}",
        headers={"Authorization": f"Bearer {access_token}",
                 "Content-Type": "application/json; charset=UTF-8"},
        json=payload if payload is not None else {},
        timeout=timeout,
    )
    try:
        body = resp.json()
    except ValueError:
        body = {"raw": resp.text[:500]}
    err = (body or {}).get("error", {}) or {}
    code = err.get("code", "ok")
    if resp.status_code != 200 or code not in ("ok", "", None):
        raise TikTokError(f"TikTok {path} failed ({resp.status_code}) {code}: {err.get('message', body)}",
                          code=code, payload=body)
    return body.get("data", {})


def get_creator_info(access_token):
    return _api("/post/publish/creator_info/query/", access_token)


# ------------------------------------------------------------------ chunks
def chunk_plan(size):
    """Returns (chunk_size, total_chunk_count, [(start, end_inclusive), ...])."""
    if size <= 0:
        raise ValueError("empty video file")
    if size > MAX_VIDEO_BYTES:
        raise ValueError(f"video is {size} bytes, TikTok max is 4 GB")
    if size < MIN_CHUNK:
        return size, 1, [(0, size - 1)]
    chunk = DEFAULT_CHUNK if size >= DEFAULT_CHUNK else size
    count = size // chunk
    while count > MAX_CHUNKS:
        chunk = min(chunk * 2, MAX_CHUNK)
        count = size // chunk
    ranges = []
    for i in range(count):
        start = i * chunk
        end = (start + chunk - 1) if i < count - 1 else size - 1
        ranges.append((start, end))
    if ranges[-1][1] - ranges[-1][0] + 1 > MAX_LAST_CHUNK:
        raise ValueError("last chunk would exceed 128 MB")
    return chunk, count, ranges


def _upload_chunks(upload_url, video_path, size, ranges, timeout=600):
    with open(video_path, "rb") as f:
        for i, (start, end) in enumerate(ranges, 1):
            f.seek(start)
            data = f.read(end - start + 1)
            for attempt in range(3):
                try:
                    r = requests.put(upload_url, data=data, timeout=timeout, headers={
                        "Content-Type": "video/mp4",
                        "Content-Length": str(len(data)),
                        "Content-Range": f"bytes {start}-{end}/{size}"})
                except requests.RequestException as e:
                    if attempt == 2:
                        raise TikTokError(f"chunk {i}/{len(ranges)} upload failed: {e}", code="upload_failed")
                    time.sleep(3 * (attempt + 1))
                    continue
                if r.status_code in (200, 201, 206):
                    break
                if r.status_code == 403:
                    raise TikTokError("upload_url expired (403); re-init the post", code="upload_url_expired")
                if attempt == 2:
                    raise TikTokError(f"chunk {i}/{len(ranges)} got HTTP {r.status_code}: {r.text[:200]}",
                                      code="upload_failed")
                time.sleep(3 * (attempt + 1))


# ------------------------------------------------------------------ helpers
def video_duration_sec(video_path):
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                              "-of", "default=nw=1:nk=1", video_path],
                             capture_output=True, text=True, timeout=60).stdout.strip()
        return float(out)
    except Exception:
        return None


def build_caption(title, description="", tags=None):
    """Caption = description (or title) + hashtags, max 2200 chars, never
    cutting a word or hashtag in half."""
    body = (description or title or "").strip()
    tag_str = " ".join(t if t.startswith("#") else f"#{t}" for t in (tags or []) if t)
    caption = f"{body}\n\n{tag_str}".strip() if tag_str else body
    if len(caption) <= CAPTION_LIMIT:
        return caption
    out = ""
    for w in caption.split(" "):
        if len(out) + len(w) + 1 > CAPTION_LIMIT:
            break
        out = f"{out} {w}" if out else w
    return out


def _poll(access_token, publish_id, done_states, timeout_sec, poll_interval_sec=5):
    deadline = time.time() + timeout_sec
    last = None
    while time.time() < deadline:
        data = _api("/post/publish/status/fetch/", access_token, {"publish_id": publish_id}, timeout=30)
        last = data
        status = data.get("status")
        if status in done_states:
            return data
        if status == "FAILED":
            raise TikTokError(f"TikTok processing failed: {data.get('fail_reason')}",
                              code="publish_failed", payload=data)
        time.sleep(poll_interval_sec)
    raise TikTokError(f"no final status within {timeout_sec}s (publish_id={publish_id}, last={last})",
                      code="status_timeout")


def _is_unaudited(err):
    text = f"{getattr(err, 'code', '')} {err}".lower()
    return "unaudited" in text or "private_account" in text


# --------------------------------------------------------------------- main
def publish_video(video_path, title, description="", tags=None, mode=None,
                  privacy_level="PUBLIC_TO_EVERYONE", timeout_sec=1800):
    """Uploads video_path to TikTok. Returns a dict with mode, publish_id,
    status, and the caption used (direct) or to paste (inbox)."""
    _load_env()
    mode = (mode or os.environ.get("TIKTOK_POST_MODE", "auto")).lower()
    if mode not in ("auto", "direct", "inbox"):
        raise ValueError(f"TIKTOK_POST_MODE must be auto/direct/inbox, got {mode!r}")
    if not os.path.isfile(video_path):
        raise TikTokError(f"video not found: {video_path}", code="missing_file")

    access_token = get_access_token()
    size = os.path.getsize(video_path)
    chunk_size, count, ranges = chunk_plan(size)
    source_info = {"source": "FILE_UPLOAD", "video_size": size,
                   "chunk_size": chunk_size, "total_chunk_count": count}
    caption = build_caption(title, description, tags)

    def _inbox():
        data = _api("/post/publish/inbox/video/init/", access_token, {"source_info": source_info})
        _upload_chunks(data["upload_url"], video_path, size, ranges)
        final = _poll(access_token, data["publish_id"],
                      {"SEND_TO_USER_INBOX", "PUBLISH_COMPLETE"}, timeout_sec)
        return {"mode": "inbox", "publish_id": data["publish_id"], "status": final.get("status"),
                "caption_to_paste": caption}

    if mode == "inbox":
        return _inbox()

    creator = get_creator_info(access_token)
    options = creator.get("privacy_level_options") or []
    if privacy_level not in options:
        if mode == "auto":
            return _inbox()
        raise TikTokError(f"privacy {privacy_level} not allowed for this account (allowed: {options})",
                          code="privacy_not_allowed", payload=creator)
    max_dur = creator.get("max_video_post_duration_sec")
    dur = video_duration_sec(video_path)
    if max_dur and dur and dur > max_dur:
        raise TikTokError(f"clip is {dur:.0f}s, this account's TikTok limit is {max_dur}s", code="too_long")

    post_info = {
        "title": caption,
        "privacy_level": privacy_level,
        "disable_comment": bool(creator.get("comment_disabled", False)),
        "disable_duet": bool(creator.get("duet_disabled", False)),
        "disable_stitch": bool(creator.get("stitch_disabled", False)),
        "video_cover_timestamp_ms": 1000,
    }
    try:
        data = _api("/post/publish/video/init/", access_token,
                    {"post_info": post_info, "source_info": source_info})
    except TikTokError as e:
        if mode == "auto" and _is_unaudited(e):
            return _inbox()
        raise
    _upload_chunks(data["upload_url"], video_path, size, ranges)
    final = _poll(access_token, data["publish_id"], {"PUBLISH_COMPLETE"}, timeout_sec)
    # TikTok's own field name is misspelled ("publicaly"); accept both.
    post_ids = final.get("publicaly_available_post_id") or final.get("publicly_available_post_id") or []
    return {"mode": "direct", "publish_id": data["publish_id"], "status": final.get("status"),
            "post_ids": post_ids, "caption": caption}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Post one video to TikTok")
    ap.add_argument("video")
    ap.add_argument("--title", default="")
    ap.add_argument("--description", default="")
    ap.add_argument("--tags", nargs="*", default=[])
    ap.add_argument("--mode", choices=["auto", "direct", "inbox"])
    ap.add_argument("--plan", action="store_true", help="print the chunk plan only, no upload")
    a = ap.parse_args()
    if a.plan:
        s = os.path.getsize(a.video)
        cs, n, r = chunk_plan(s)
        print(json.dumps({"size": s, "chunk_size": cs, "total_chunk_count": n, "ranges": r}, indent=1))
    else:
        print(json.dumps(publish_video(a.video, a.title, a.description, a.tags, a.mode), indent=2))
