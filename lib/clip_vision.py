#!/usr/bin/env python3
"""
lib/clip_vision.py <clip.mp4> <out_json> [--transcript path/to/script.json]

Looks at ONE finished clip the way a viewer would: 6 frames spread across it
plus the transcript, sent to a vision model. Returns what actually happened,
the game, the moment type, a recommended cover/hook frame, a caption-ready
one-line summary, and a standards verdict:

  {"game", "what_happened", "summary_line", "moment_type", "hook_t",
   "standards": {"action": 0-10, "clarity": 0-10, "payoff": 0-10, "dead_space": 0-10},
   "score": 0-100, "verdict": "keep"|"cut", "reason"}

"cut" means the clip doesn't meet the bar (nothing happens, mostly menus or
loading, no payoff, unreadable). The publish step holds cut clips back
instead of posting them. The output also feeds metadata generation, so
titles and captions describe what's on screen, not just what was said.
"""
import argparse
import base64
import json
import os
import subprocess
import sys
import tempfile
import shutil

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
MOMENT_TYPES = ["CLUTCH", "FAIL", "FUNNY", "HYPE", "RAGE", "REACTION", "WIN", "LOSS", "INSANE_PLAY",
                "TUTORIAL", "STORY", "JOKE", "TRASH_TALK", "SURPRISE", "OTHER"]
CUT_BELOW = int(os.environ.get("CLIP_STANDARD_MIN", 55))


def _duration(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                       capture_output=True, text=True, timeout=60)
    return float(r.stdout.strip() or 0)


def keyframes(clip, n=6, width=640, tmp=None):
    d = _duration(clip)
    tmp = tmp or tempfile.mkdtemp(prefix="cv_")
    out = []
    for i in range(n):
        t = round(d * (i + 0.5) / n, 2)
        p = os.path.join(tmp, f"k{i}.jpg")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(t), "-i", clip, "-frames:v", "1",
                        "-vf", f"scale={width}:-2", "-q:v", "4", p], check=True, timeout=60)
        if os.path.exists(p):
            out.append((t, p))
    return out, d


def describe(clip, transcript="", client=None):
    if client is None:
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY not set")
        import anthropic
        client = anthropic.Anthropic(api_key=key)
    from ai_router import model_for_task
    tmp = tempfile.mkdtemp(prefix="cv_")
    try:
        frames, dur = keyframes(clip, tmp=tmp)
        content = []
        for t, p in frames:
            content.append({"type": "text", "text": f"t={t}s"})
            with open(p, "rb") as fh:
                content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                             "data": base64.b64encode(fh.read()).decode()}})
        content.append({"type": "text", "text": f"""These are 6 frames, in order, from one {dur:.0f}-second short-form clip cut from a livestream.
Transcript of the clip (may be empty): {transcript[:2500]!r}

Judge it like a strict short-form editor. Respond with ONLY JSON:
{{"game": "<exact game title or null>",
 "what_happened": "<2 sentences: what literally happens on screen, grounded in the frames and transcript>",
 "summary_line": "<one punchy caption-ready line, no hashtags>",
 "moment_type": one of {MOMENT_TYPES},
 "hook_t": <seconds of the most striking frame for the cover/thumbnail>,
 "standards": {{"action": 0-10, "clarity": 0-10, "payoff": 0-10, "dead_space": 0-10}},
 "reason": "<one sentence on why it is or isn't worth posting>"}}
dead_space = how much of the clip is menus, loading, waiting, black or nothing happening (10 = all of it)."""})
        msg = client.messages.create(model=model_for_task("clip_vision"), max_tokens=700,
                                     messages=[{"role": "user", "content": content}])
        raw = msg.content[0].text
        data = json.loads(raw[raw.index("{"): raw.rindex("}") + 1])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    s = data.get("standards") or {}
    g = lambda k: max(0, min(10, float(s.get(k, 0) or 0)))
    # weighted: payoff matters most, dead space counts against
    score = round(10 * (0.3 * g("action") + 0.2 * g("clarity") + 0.35 * g("payoff") + 0.15 * (10 - g("dead_space"))))
    data["score"] = score
    # The bar a paying customer expects: something real happens. Cut when the
    # score is low, when the clip is mostly dead space, or when there's
    # neither action nor a payoff (talking over nothing, idle walking, menus).
    no_moment = g("action") < 4 and g("payoff") < 5
    data["verdict"] = "cut" if (score < CUT_BELOW or g("dead_space") >= 6 or no_moment) else "keep"
    data["cut_reason"] = None if data["verdict"] == "keep" else (
        "mostly dead space" if g("dead_space") >= 6 else "no real moment (low action and payoff)" if no_moment else "below the quality bar")
    data["duration"] = round(dur, 2)
    return data


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("clip"); ap.add_argument("out_json"); ap.add_argument("--transcript", default="")
    a = ap.parse_args()
    text = ""
    if a.transcript and os.path.exists(a.transcript):
        try:
            text = json.load(open(a.transcript)).get("script_text", "")
        except Exception:
            pass
    data = describe(a.clip, text)
    json.dump(data, open(a.out_json, "w"), indent=2)
    print(json.dumps({k: data.get(k) for k in ("game", "moment_type", "score", "verdict")}))


if __name__ == "__main__":
    main()
