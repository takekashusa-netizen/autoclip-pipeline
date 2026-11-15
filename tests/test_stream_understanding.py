"""End-to-end checks for stream understanding, clip vision, trends, metadata context and the standards gate.
Run: python3 tests/test_stream_understanding.py   (needs ffmpeg + tesseract; no API key or network needed)"""
import json, os, subprocess, sys, tempfile, shutil
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
sys.path.insert(0, os.path.join(ROOT, "skills", "clip-select"))
import stream_understanding as SU
import clip_vision as CV
import gaming_trends as GT

TMP = tempfile.mkdtemp(prefix="su_test_")


def make_stream():
    """0-120s game A (moving), 120-180s black, 180-240s 'LOADING' card, 240-360s game B (moving)."""
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", (1280, 720), (30, 30, 40))
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", 120)
    except Exception:
        font = ImageFont.load_default(size=120)
    d.text((300, 280), "LOADING...", fill=(255, 255, 255), font=font)
    card = os.path.join(TMP, "loading.png"); img.save(card)
    parts = []
    def run(args, out):
        subprocess.run(["ffmpeg", "-v", "error", "-y"] + args + ["-pix_fmt", "yuv420p", "-r", "10", out], check=True)
        parts.append(out)
    run(["-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=10", "-t", "120"], os.path.join(TMP, "a.mp4"))
    run(["-f", "lavfi", "-i", "color=c=black:size=1280x720:rate=10", "-t", "60"], os.path.join(TMP, "b.mp4"))
    run(["-loop", "1", "-i", card, "-t", "60"], os.path.join(TMP, "c.mp4"))
    run(["-f", "lavfi", "-i", "mandelbrot=size=1280x720:rate=10", "-t", "120"], os.path.join(TMP, "d.mp4"))
    lst = os.path.join(TMP, "list.txt")
    open(lst, "w").write("".join(f"file '{p}'\n" for p in parts))
    out = os.path.join(TMP, "stream.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", out], check=True)
    return out


class FakeMsg:
    def __init__(self, text): self.content = [type("C", (), {"text": text})()]


class FakeVisionClient:
    """Stands in for the Claude API: labels frames like a vision model would."""
    def __init__(self): self.calls = 0; self.messages = self
    def create(self, model, max_tokens, messages):
        self.calls += 1
        ts = [float(c["text"].split("=")[1].rstrip("s:")) for c in messages[0]["content"]
              if c["type"] == "text" and c["text"].startswith("Frame at t=")]
        rows = []
        for t in ts:
            if t < 120: rows.append({"t": t, "game": "Call of Duty: Warzone", "scene": "gameplay", "action": 2 if 40 < t < 80 else 1, "what": "squad fight"})
            elif t < 180: rows.append({"t": t, "game": None, "scene": "other", "action": 0, "what": "black"})
            elif t < 240: rows.append({"t": t, "game": None, "scene": "other", "action": 0, "what": "text card"})
            else: rows.append({"t": t, "game": "NBA 2K27", "scene": "gameplay", "action": 1, "what": "park game"})
        return FakeMsg(json.dumps(rows))


passed = 0
def ok(c, m):
    global passed
    if not c:
        print("FAIL:", m); sys.exit(1)
    passed += 1; print("ok -", m)


video = make_stream()
client = FakeVisionClient()
tl = SU.analyze(video, every=10, hint_games=["Warzone"], client=client)
games = {g["game"] for g in tl["games"]}
ok(tl["vision"] and client.calls >= 4, f"vision labels used ({client.calls} batched calls for {len(tl['samples'])} frames)")
ok(games == {"Call of Duty: Warzone", "NBA 2K27"}, f"both games identified: {games}")
ok(len(tl["switches"]) == 1 and tl["switches"][0]["to"] == "NBA 2K27", f"game switch detected at ~{tl['switches'][0]['t']}s")
ok(SU.dead_ratio(tl, 125, 175) > 0.9, "black screen flagged as dead space")
ok(SU.dead_ratio(tl, 185, 235) > 0.9, "LOADING card flagged as dead space (OCR)")
ok(SU.dead_ratio(tl, 10, 110) < 0.1 and SU.dead_ratio(tl, 250, 350) < 0.1, "gameplay is not marked dead")
ok(100 <= tl["dead_seconds"] <= 140, f"dead seconds ≈ 120 ({tl['dead_seconds']})")

# local-only fallback (no API key): still finds dead space
tl_local = SU.analyze(video, every=10, client=None) if not os.environ.get("ANTHROPIC_API_KEY") else tl
ok(SU.dead_ratio(tl_local, 125, 175) > 0.9 and SU.dead_ratio(tl_local, 185, 235) > 0.6, "dead space still detected without any API key")

# best_windows uses the timeline: windows avoid dead space and never straddle the switch
import best_windows as BW
duration = tl["duration"]
scores, bin_sec = BW.build_interest_timeline(duration, [], None, None, stream_timeline=tl)
wins = BW.find_best_windows(scores, bin_sec, 60, 3, min_score_per_min=0)
for w in wins:
    ok(SU.dead_ratio(tl, w["start"], w["end"]) == 0 and len(SU.games_in(tl, w["start"], w["end"])) == 1,
       f"window {w['start']}-{w['end']}s: no dead space, one game ({SU.games_in(tl, w['start'], w['end'])})")

# clip vision verdicts
class FakeClipClient:
    def __init__(self, standards): self.s = standards; self.messages = self
    def create(self, **kw):
        return FakeMsg(json.dumps({"game": "Call of Duty: Warzone", "what_happened": "x", "summary_line": "y",
                                   "moment_type": "CLUTCH", "hook_t": 3, "standards": self.s, "reason": "r"}))
clip = os.path.join(TMP, "a.mp4")
good = CV.describe(clip, client=FakeClipClient({"action": 9, "clarity": 8, "payoff": 9, "dead_space": 1}))
bad = CV.describe(clip, client=FakeClipClient({"action": 2, "clarity": 6, "payoff": 1, "dead_space": 8}))
ok(good["verdict"] == "keep" and good["score"] >= 80, f"strong clip kept (score {good['score']})")
ok(bad["verdict"] == "cut", f"dead/no-payoff clip cut (score {bad['score']})")
quiet = CV.describe(clip, client=FakeClipClient({"action": 3, "clarity": 9, "payoff": 4, "dead_space": 2}))
ok(quiet["verdict"] == "cut" and "no real moment" in quiet["cut_reason"], "clean-looking but uneventful clip is cut (no real moment)")
quiet_bins = [0.0] * 60 + [40.0] * 12 + [0.0] * 60   # 5s bins: a 1-minute burst inside 10 quiet minutes
qw = BW.find_best_windows(quiet_bins, 5.0, 60, 3, min_score_per_min=15.0)
ok(len(qw) == 1 and qw[0]["start"] == 300.0, f"only the real moment is clipped; quiet stretches are not padded in ({len(qw)} window)")

# trends (no network here -> seed); fuzzy match
GT.CACHE = os.path.join(TMP, "trends.json")
t = GT.load()
ok(t["games"] and GT.trend_rank("Warzone", t) and GT.trend_rank("Some Unknown Game", t) is None, f"trending list loaded from {t['source']}, fuzzy match works")

# metadata context: platform-suffixed queue ids resolve to the real sub-job + clip vision
import generate_clip_metadata as G
G.PIPELINE_ROOT = TMP
d = os.path.join(TMP, "projects", "job1__window07", "rough-cut"); os.makedirs(d)
json.dump(bad, open(os.path.join(d, "clip-vision.json"), "w"))
ok(any(os.path.exists(os.path.join(x, "clip-vision.json")) for x in G._context_dirs("job1_window07_tiktok")),
   "suffixed id (job1_window07_tiktok) finds the clip's data — fixes the 'no transcript' failures")
captured = {}
G.generate_clip_metadata_from_text = lambda text, platform, visual=None: captured.update(text=text, visual=visual) or {"title": "t", "description": "d", "hashtags": []}
G.generate_clip_metadata("job1_window07_tiktok", "tiktok")
ok(captured["visual"]["moment_type"] == "CLUTCH", "metadata generation receives what's on screen")

# standards gate holds a 'cut' clip instead of posting it
import publish_scheduler as PS
from datetime import datetime, timedelta
q = [{"platform": "tiktok", "content_id": "job1__window07", "video_path": clip, "title": "t", "description": "d",
      "tags": [], "status": "pending", "scheduled_time": (datetime.now() - timedelta(minutes=1)).isoformat()}]
PS._load_queue = lambda: q
PS._save_queue = lambda qq: None
PS._record_metadata_failure = lambda *a, **k: None
sys.modules["generate_clip_metadata"] = G
out = PS.process_due_items()
ok(q[0]["status"] == "held_standards", f"standards gate held the weak clip: {q[0].get('error')}")

shutil.rmtree(TMP, ignore_errors=True)
print(f"\nALL {passed} CHECKS PASS")
