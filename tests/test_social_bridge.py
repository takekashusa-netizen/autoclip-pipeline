"""python3 tests/test_social_bridge.py — bridge never posts in dry run, blocks duplicates, isolates platform failures."""
import os, sys, types, importlib
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "worker")); sys.path.insert(0, os.path.join(ROOT, "lib"))
calls = []
fake_yt = types.ModuleType("youtube_publish"); fake_yt.upload_video = lambda *a, **k: calls.append(("yt", k.get("privacy_status"))) or {"url": "https://youtu.be/abc"}
fake_tt = types.ModuleType("tiktok_publish")
def tt(*a, **k): raise RuntimeError("tiktok down")
fake_tt.publish_video = tt
fake_dup = types.ModuleType("dup_guard"); fake_dup.check = lambda cid, platform: (platform != "tiktok" or cid != "dup", "92% match"); fake_dup.mark = lambda *a, **k: calls.append(("mark", k.get("platform")))
sys.modules.update({"youtube_publish": fake_yt, "tiktok_publish": fake_tt, "dup_guard": fake_dup})
os.environ["TAKEKASH_OWNER_TOKEN"] = "x"
import social_bridge as B
reports = []; B.api = lambda path, body=None: reports.append(body) or {"posts": []}
B.download = lambda url: "/tmp/nonexistent.mp4"
post = {"id": "p1", "platforms": ["youtube", "tiktok"], "title": "T", "caption": "c #warzone", "mediaUrl": "https://x/a.mp4", "contentId": "ok"}
B.LIVE = False; B.post_one(post)
assert calls == [] and reports == [], "dry run posts and reports nothing"
B.LIVE = True; B.post_one(post)
assert ("yt", "private") in calls, "YouTube goes up PRIVATE"
st = {r["platform"]: r["status"] for r in reports}
assert st == {"youtube": "posted", "tiktok": "failed"}, st
assert ("mark", "youtube") in calls and ("mark", "tiktok") not in calls, "only successful posts are marked for the duplicate gate"
reports.clear(); calls.clear(); B.post_one({**post, "platforms": ["tiktok"], "contentId": "dup"})
assert reports[0]["status"] == "blocked" and not calls, "duplicate blocked, nothing posted"
print("social bridge: all checks passed")
