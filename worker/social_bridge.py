"""Posting bridge: takes due posts from the TakeKash Admin Hub calendar and posts them from the owner's Mac
with the pipeline's own posters (lib/youtube_publish.py, lib/tiktok_publish.py) and duplicate gate (lib/dup_guard.py).
Account sign-ins stay on this Mac; the website never holds YouTube or TikTok keys.

  TAKEKASH_OWNER_TOKEN=<Admin Hub sign-in token> python worker/social_bridge.py           # dry run (default): posts nothing
  TAKEKASH_OWNER_TOKEN=... SOCIAL_LIVE=1 python worker/social_bridge.py                    # really posts
  TAKEKASH_OWNER_TOKEN=... SOCIAL_LIVE=1 python worker/social_bridge.py --loop             # every 5 minutes

Safety: YouTube uploads go up PRIVATE (review in YouTube Studio, then publish). TikTok uses the poster's "auto" mode:
public only if TikTok has approved the app, otherwise a draft in the TikTok app inbox. A clip whose words match one
already posted on that platform is blocked and reported, never posted.
"""
import json
import os
import sys
import tempfile
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
SITE = os.environ.get("TAKEKASH_SITE", "https://takekash.netlify.app").rstrip("/")
LIVE = os.environ.get("SOCIAL_LIVE") == "1"


def log(m):
    print(f"[social-bridge] {m}", flush=True)


def api(path, body=None):
    token = os.environ.get("TAKEKASH_OWNER_TOKEN")
    if not token:
        sys.exit("Set TAKEKASH_OWNER_TOKEN (the t=... value from your Admin Hub sign-in link).")
    req = urllib.request.Request(SITE + path, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                                          "User-Agent": "takekash-social-bridge"}, method="POST" if body is not None else "GET")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def report(post_id, platform, status, **kw):
    if not LIVE:
        log(f"  (dry run) would report {platform}: {status} {kw}")
        return
    api("/api/social-queue/result", {"id": post_id, "platform": platform, "status": status, **kw})


def download(url):
    if not url.startswith("https://"):
        raise ValueError("video link must be https")
    fd, path = tempfile.mkstemp(suffix=".mp4")
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "takekash-social-bridge"}), timeout=600) as r, os.fdopen(fd, "wb") as f:
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
    return path


def post_one(p):
    log(f"post {p['id']}: {', '.join(p['platforms'])} — {(p.get('title') or p['caption'])[:60]}")
    video = None
    try:
        for platform in p["platforms"]:
            if p.get("contentId"):
                import dup_guard
                ok, why = dup_guard.check(p["contentId"], platform=platform)
                if not ok:
                    log(f"  {platform}: BLOCKED duplicate — {why}")
                    report(p["id"], platform, "blocked", note=why)
                    continue
            if not LIVE:
                log(f"  {platform}: dry run, nothing posted")
                continue
            video = video or download(p["mediaUrl"])
            try:
                if platform == "youtube":
                    import youtube_publish
                    tags = [w.lstrip("#") for w in p["caption"].split() if w.startswith("#")][:15]
                    r = youtube_publish.upload_video(video, (p.get("title") or p["caption"])[:100], p["caption"], tags, privacy_status="private")
                    report(p["id"], "youtube", "posted", url=r.get("url"), note="uploaded PRIVATE: publish it in YouTube Studio")
                elif platform == "tiktok":
                    import tiktok_publish
                    r = tiktok_publish.publish_video(video, p.get("title") or "", p["caption"])
                    report(p["id"], "tiktok", "inbox" if r.get("mode") == "inbox" else "posted",
                           note="draft in the TikTok app inbox: paste the caption and post" if r.get("mode") == "inbox" else None)
                if p.get("contentId"):
                    import dup_guard
                    dup_guard.mark(p["contentId"], platform=platform, note=f"takekash post {p['id']}")
            except Exception as e:  # one platform failing never stops the others
                log(f"  {platform}: FAILED {e}")
                report(p["id"], platform, "failed", error=str(e)[:300])
    finally:
        if video and os.path.exists(video):
            os.remove(video)


def run_once():
    posts = api("/api/social-queue" + ("" if LIVE else "?peek=1"))["posts"]
    log(f"{len(posts)} due post(s){'' if LIVE else ' — DRY RUN, set SOCIAL_LIVE=1 to really post'}")
    for p in posts:
        post_one(p)


if __name__ == "__main__":
    if "--loop" in sys.argv:
        while True:
            try:
                run_once()
            except Exception as e:
                log(f"error: {e}")
            time.sleep(300)
    else:
        run_once()
