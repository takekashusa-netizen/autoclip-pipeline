#!/usr/bin/env python3
"""
lib/stream_understanding.py <video> <out_json> [--every SEC] [--hint "Warzone,Apex Legends"]

Whole-VOD understanding, before any clip is picked:
  * WHICH GAME is on screen, minute by minute, so a stream that switches
    games (Warzone -> 2K -> Just Chatting) is split correctly and each part
    gets the right game, HUD reader and tags.
  * WHAT KIND OF SCENE it is: gameplay, menu, loading, lobby/matchmaking,
    death/spectate, cutscene, just chatting, BRB/starting-soon/ending
    screens, desktop.
  * DEAD SPACE: everything not worth clipping (menus, loading, queues,
    BRB/AFK, black or frozen screens, long static stretches).

Two layers, so it always produces something:
  1. Local signals (free, always on): black frames, frozen/static frames
     (AFK), and on-screen text via tesseract ("LOADING", "BE RIGHT BACK",
     "STARTING SOON", "FINDING MATCH", "PRESS ANY BUTTON", ...).
  2. Vision labels (when ANTHROPIC_API_KEY is set): batches of small
     keyframes go to a fast Claude model that names the game, the scene
     type, the action level and a one-line description of what's on
     screen. Cost stays low: one 512px frame every N seconds, 8 per call.

Output JSON:
  {"samples": [{"t", "game", "scene", "action", "what", "dead", "why"}],
   "segments": [{"start", "end", "game", "scene", "dead", "why"}],
   "games": [{"game", "seconds"}], "switches": [{"t", "from", "to"}],
   "dead_seconds", "duration", "vision": bool}
"""
import argparse
import base64
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

DEAD_SCENES = {"menu", "loading", "lobby", "matchmaking", "brb_screen", "starting_soon",
               "ending_screen", "desktop", "black", "static"}
SCENES = ["gameplay", "death_spectate", "cutscene", "just_chatting", "menu", "loading", "lobby",
          "matchmaking", "brb_screen", "starting_soon", "ending_screen", "desktop", "other"]
DEAD_TEXT = [
    (r"\bloading\b|\bconnecting\b|\bjoining\b|\binstalling\b|\bdownloading\b|\bplease wait\b", "loading"),
    (r"be right back|\bbrb\b|\baway from keyboard\b|\bafk\b|\bintermission\b", "brb_screen"),
    (r"starting soon|stream (will )?start|going live", "starting_soon"),
    (r"stream (has )?ended|thanks for watching|see you next", "ending_screen"),
    (r"finding (a )?match|matchmaking|searching for|in queue|waiting for players|ready up", "matchmaking"),
    (r"press any (button|key)|main menu|\bsettings\b|\bloadouts?\b|\bbattle pass\b|\bstore\b|\blocker\b|\bplay now\b", "menu"),
]


# ---------- frame sampling ----------

def probe_duration(video):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", video],
                         capture_output=True, text=True, timeout=60)
    try:
        return float(out.stdout.strip())
    except ValueError:
        return 0.0


def sample_frames(video, every=20.0, width=512, tmp=None):
    """One small JPEG every `every` seconds. Returns [(t, path)]."""
    tmp = tmp or tempfile.mkdtemp(prefix="su_")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", video, "-vf", f"fps=1/{every},scale={width}:-2",
                    "-q:v", "5", os.path.join(tmp, "f_%06d.jpg")], check=True, timeout=3600)
    files = sorted(f for f in os.listdir(tmp) if f.startswith("f_"))
    # fps filter emits frame k at ~ (k - 0.5) * every; use the midpoint of each sampled span
    return [(round((i + 0.5) * every, 2), os.path.join(tmp, f)) for i, f in enumerate(files)]


def _gray_small(path):
    """64x36 grayscale bytes via ffmpeg (no OpenCV needed)."""
    out = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-vf", "scale=64:36,format=gray", "-f", "rawvideo", "-"],
                         capture_output=True, timeout=30)
    return out.stdout


def local_signals(frames):
    """Black / static / on-screen dead text for each sampled frame."""
    texts = {}
    if shutil.which("tesseract") and frames:
        try:
            sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            from studio.game_events import _ocr_batch  # batched: one tesseract process for all frames
            for (t, _), txt in zip(frames, _ocr_batch([p for _, p in frames], psm=11)):
                texts[t] = (txt or "").lower()
        except Exception:
            for t, p in frames:
                r = subprocess.run(["tesseract", p, "-", "--psm", "11"], capture_output=True, text=True, timeout=30)
                texts[t] = r.stdout.lower()
    out, prev = [], None
    for t, p in frames:
        g = _gray_small(p)
        mean = sum(g) / len(g) if g else 0
        diff = (sum(abs(a - b) for a, b in zip(g, prev)) / len(g)) if (prev and g and len(prev) == len(g)) else None
        prev = g
        sig = {"t": t, "luma": round(mean, 1), "diff": None if diff is None else round(diff, 2), "text_hit": None}
        txt = texts.get(t, "")
        for pat, scene in DEAD_TEXT:
            if re.search(pat, txt):
                sig["text_hit"] = scene
                break
        out.append(sig)
    return out


# ---------- vision labels ----------

def _client():
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    try:
        import anthropic
        return anthropic.Anthropic(api_key=key)
    except Exception:
        return None


def vision_labels(frames, hint_games=(), client=None, batch=8):
    """Label frames with game/scene/action/what via a fast vision model. {} if unavailable."""
    client = client or _client()
    if not client or not frames:
        return {}
    from ai_router import model_for_task
    model = model_for_task("frame_labeling")
    labels = {}
    hint = ", ".join(hint_games) if hint_games else "none given"
    for i in range(0, len(frames), batch):
        chunk = frames[i:i + batch]
        content = []
        for t, p in chunk:
            content.append({"type": "text", "text": f"Frame at t={t}s:"})
            with open(p, "rb") as fh:
                content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                             "data": base64.b64encode(fh.read()).decode()}})
        content.append({"type": "text", "text": (
            "These are frames from a livestream VOD. For EACH frame return one object:\n"
            '{"t": <seconds as given>, "game": "<exact official game title, or null if no game is on screen>", '
            f'"scene": one of {SCENES}, "action": 0-3 (0 nothing happening, 3 intense fight/score/big moment), '
            '"what": "<= 15 words, what is literally on screen"}\n'
            "Identify the game from the actual HUD, art style, menus and UI, not from guesses. Webcam overlays "
            "do not change the scene type. A stream's 'starting soon' / 'be right back' cards are brb_screen / "
            f"starting_soon. Games this streamer usually plays (hint only): {hint}.\n"
            'Respond with ONLY a JSON array.')})
        try:
            msg = client.messages.create(model=model, max_tokens=1500, messages=[{"role": "user", "content": content}])
            raw = msg.content[0].text
            arr = json.loads(raw[raw.index("["): raw.rindex("]") + 1])
            for row in arr:
                if isinstance(row, dict) and "t" in row:
                    labels[float(row["t"])] = row
        except Exception as e:  # one bad batch never sinks the run
            print(f"stream_understanding: vision batch at t={chunk[0][0]} failed: {e}", file=sys.stderr)
    return labels


# ---------- timeline ----------

def classify(sig, label, static_streak):
    scene = (label or {}).get("scene") or "other"
    game = (label or {}).get("game") or None
    why = None
    if sig["luma"] < 12:
        scene, why = "black", "black screen"
    elif sig["text_hit"] and scene not in ("gameplay", "death_spectate"):
        scene, why = sig["text_hit"], f"on-screen text ({sig['text_hit']})"
    elif static_streak >= 3 and scene not in ("just_chatting",):
        scene, why = "static", "frozen/unchanged picture (AFK)"
    if scene not in SCENES + ["black", "static"]:
        scene = "other"
    dead = scene in DEAD_SCENES
    if dead and not why:
        why = scene.replace("_", " ")
    return game, scene, dead, why


def _smooth(values, k=1):
    """Majority vote over a +/-k window; removes one-frame flickers (a single misread frame)."""
    out = []
    for i in range(len(values)):
        win = values[max(0, i - k): i + k + 1]
        out.append(Counter(win).most_common(1)[0][0])
    return out


def build_timeline(sigs, labels, every, duration):
    samples, streak = [], 0
    for s in sigs:
        streak = streak + 1 if (s["diff"] is not None and s["diff"] < 1.0) else 0
        lab = labels.get(s["t"])
        game, scene, dead, why = classify(s, lab, streak)
        samples.append({"t": s["t"], "game": game, "scene": scene, "action": int((lab or {}).get("action") or 0),
                        "what": (lab or {}).get("what"), "dead": dead, "why": why})
    # carry the last known game across dead frames (a loading screen is still "in Warzone")
    last = None
    for s in samples:
        if s["game"]:
            last = s["game"]
        elif last and s["scene"] not in ("just_chatting", "brb_screen", "starting_soon", "ending_screen", "desktop"):
            s["game"] = last
    games = _smooth([s["game"] or "" for s in samples])
    deads = _smooth([s["dead"] for s in samples])
    for s, g, d in zip(samples, games, deads):
        s["game"], s["dead"] = (g or None), d
        if not d and s["why"] and s["scene"] in DEAD_SCENES:
            s["why"] = None  # a lone dead-looking frame inside live action
    segs = []
    for s in samples:
        start = max(0.0, s["t"] - every / 2)
        end = min(duration or s["t"] + every / 2, s["t"] + every / 2)
        key = (s["game"], s["dead"])
        if segs and (segs[-1]["game"], segs[-1]["dead"]) == key:
            segs[-1]["end"] = round(end, 2)
            segs[-1]["_scenes"].append(s["scene"])
        else:
            segs.append({"start": round(start, 2), "end": round(end, 2), "game": s["game"], "dead": s["dead"],
                         "why": s["why"], "_scenes": [s["scene"]]})
    for g in segs:
        g["scene"] = Counter(g.pop("_scenes")).most_common(1)[0][0]
    switches = []
    prev_game = None
    for g in segs:
        if g["dead"] or not g["game"]:
            continue
        if prev_game and g["game"] != prev_game:
            switches.append({"t": g["start"], "from": prev_game, "to": g["game"]})
        prev_game = g["game"]
    tally = Counter()
    for g in segs:
        if g["game"] and not g["dead"]:
            tally[g["game"]] += g["end"] - g["start"]
    return {"samples": samples, "segments": segs, "switches": switches,
            "games": [{"game": k, "seconds": round(v, 1)} for k, v in tally.most_common()],
            "dead_seconds": round(sum(g["end"] - g["start"] for g in segs if g["dead"]), 1)}


def analyze(video, every=20.0, hint_games=(), client=None):
    duration = probe_duration(video)
    tmp = tempfile.mkdtemp(prefix="su_")
    try:
        frames = sample_frames(video, every=every, tmp=tmp)
        sigs = local_signals(frames)
        labels = vision_labels(frames, hint_games=hint_games, client=client)
        tl = build_timeline(sigs, labels, every, duration)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    tl.update({"duration": round(duration, 2), "every": every, "vision": bool(labels)})
    return tl


# ---------- helpers for clip selection ----------

def dead_ratio(timeline, start, end):
    total = max(0.001, end - start)
    dead = sum(max(0.0, min(end, g["end"]) - max(start, g["start"])) for g in timeline.get("segments", []) if g["dead"])
    return dead / total


def game_at(timeline, t):
    for g in timeline.get("segments", []):
        if g["start"] <= t < g["end"]:
            return g["game"]
    return None


def games_in(timeline, start, end):
    return sorted({g["game"] for g in timeline.get("segments", [])
                   if g["game"] and not g["dead"] and g["end"] > start and g["start"] < end})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video"); ap.add_argument("out_json")
    ap.add_argument("--every", type=float, default=float(os.environ.get("STREAM_SAMPLE_SEC", 20)))
    ap.add_argument("--hint", default=os.environ.get("STREAM_GAME_HINTS", "Call of Duty: Warzone,Apex Legends,NBA 2K27,Call of Duty: Modern Warfare 4"))
    a = ap.parse_args()
    tl = analyze(a.video, every=a.every, hint_games=[h.strip() for h in a.hint.split(",") if h.strip()])
    json.dump(tl, open(a.out_json, "w"), indent=2)
    print(json.dumps({"games": tl["games"], "switches": len(tl["switches"]), "dead_seconds": tl["dead_seconds"],
                      "duration": tl["duration"], "vision": tl["vision"]}))


if __name__ == "__main__":
    main()
