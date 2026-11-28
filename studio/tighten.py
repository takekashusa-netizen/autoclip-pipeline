"""Tighten: viral pacing from timestamped words, a word-aligned hook, a storyboard, then an FFmpeg render.

Everything is decided from the transcript's word timestamps (no guessing from raw video):
  1. PACING  cut dead air longer than GAP_MAX and isolated filler words (um, uh, er, ah, hmm), padding
             every kept span by PAD so no word is clipped; spans shorter than MIN_KEEP merge into neighbours.
  2. HOOK    split speech into sentences (punctuation or a pause > SENT_GAP), score each by strict rules:
             question/why/how/what (+3), a number (+2), strong words (+2 each, max 4), "!" (+1),
             loudness above the clip's median (+0..2), 1.2-4.0 s long (else -3), not already in the first 1 s.
             The best sentence scoring >= HOOK_MIN becomes a cold open (hook, then the tightened body).
  3. PLAN    <stem>.cutlist.json: every shot with source in/out, output in/out, role, spoken text, plus stats;
             <stem>.storyboard.jpg: one timecoded frame per shot (max 12). Nothing renders until the plan is
             approved (approve() locks a fingerprint of the cut list), unless force=True (unattended tiers).
  4. RENDER  one ffmpeg filter graph: trim/atrim per shot, 12 ms audio fades at every cut, concat.
"""
import hashlib
import json
import os
import re

from .common import AUDIO_ENC, VIDEO_ENC, StudioError, ffmpeg, font, load_words, probe, run

GAP_MAX = 0.35      # silence longer than this is dead air
PAD = 0.08          # keep this much around every word
MIN_KEEP = 0.25     # shorter kept spans are merged
SENT_GAP = 0.6      # a pause this long ends a sentence
HOOK_MIN = 3        # minimum hook score to cold-open
FILLERS = {"um", "uh", "uhh", "umm", "er", "erm", "ah", "hmm", "mm"}
STRONG = {"never", "insane", "crazy", "secret", "best", "worst", "nobody", "everybody", "everyone", "watch", "wait",
          "no", "way", "clutch", "won", "lost", "money", "free", "first", "last", "only", "biggest", "why", "stop",
          "bro", "literally", "actually", "impossible", "broke", "rich", "million", "hack", "mistake", "truth"}


def _clean(w): return re.sub(r"[^\w']", "", w.lower())


def pacing(words, dur, is_loud=None):
    """kept spans [(a, b)] covering speech, dead air and isolated fillers removed.
    is_loud(a, b) -> True keeps a no-speech gap anyway: on gaming clips the play happens between words."""
    ws = [w for w in words if _clean(w["word"]) not in FILLERS and w["end"] > w["start"]]
    if not ws:
        return [(0.0, dur)], {"fillers": 0}
    spans = []
    a, b = max(0.0, ws[0]["start"] - PAD), ws[0]["end"] + PAD
    for w in ws[1:]:
        if w["start"] - b + PAD > GAP_MAX and not (is_loud and is_loud(b, w["start"] - PAD)):
            spans.append((a, b)); a = max(0.0, w["start"] - PAD)
        b = max(b, w["end"] + PAD)
    if is_loud and dur - b > GAP_MAX and is_loud(b, dur):   # loud tail after the last word (the payoff) stays
        b = dur
    spans.append((a, min(dur, b)))
    merged = []
    for s in spans:
        if merged and (s[1] - s[0] < MIN_KEEP or s[0] - merged[-1][1] < 0.05):
            merged[-1] = (merged[-1][0], max(merged[-1][1], s[1]))
        else:
            merged.append(s)
    return [(round(x, 3), round(y, 3)) for x, y in merged], {"fillers": len(words) - len(ws)}


def sentences(words):
    words = [w for w in words if _clean(w["word"]) not in FILLERS]      # a hook never starts on "um"
    out, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        if re.search(r"[.!?]$", w["word"].strip()) or nxt is None or nxt["start"] - w["end"] > SENT_GAP:
            out.append(cur); cur = []
    return [{"start": s[0]["start"], "end": s[-1]["end"], "text": " ".join(x["word"].strip() for x in s)} for s in out if s]


def score_hook(s, loud=None):
    t = s["text"]; toks = [_clean(x) for x in t.split()]; d = s["end"] - s["start"]; why = []
    sc = 0
    if "?" in t or (toks and toks[0] in {"why", "how", "what", "who", "when", "where"}): sc += 3; why.append("question")
    if re.search(r"\d|\b(one|two|three|ten|hundred|thousand|million)\b", t.lower()): sc += 2; why.append("number")
    strong = [x for x in toks if x in STRONG]
    if strong: sc += min(4, 2 * len(strong)); why.append("strong:" + ",".join(sorted(set(strong))))
    if "!" in t: sc += 1; why.append("exclaim")
    if loud is not None: sc += loud; why.append(f"loud+{loud}") if loud else None
    if not 1.2 <= d <= 4.0: sc -= 3; why.append("bad-length")
    if s["start"] < 1.0: sc -= 10; why.append("already-first")
    return sc, why


def loud_gaps(clip, ratio=1.3):
    """True when a span's audio is clearly louder than the clip's median (game audio, a crowd, a hit)"""
    try:
        import numpy as np
        from .common import read_audio_mono, rms_envelope
        env = rms_envelope(read_audio_mono(clip, 16000), 16000, 0.1); med = float(np.median(env)) + 1e-9
    except Exception:
        return None
    def f(a, b):
        seg = env[int(a * 10): max(int(a * 10) + 1, int(b * 10))]
        return bool(len(seg)) and float(np.percentile(seg, 75)) > med * ratio
    return f


def _loudness(clip, sents):
    try:
        import numpy as np
        from .common import read_audio_mono, rms_envelope
        a = read_audio_mono(clip, 16000); env = rms_envelope(a, 16000, 0.1); med = float(np.median(env)) + 1e-9
        out = []
        for s in sents:
            seg = env[int(s["start"] * 10): max(int(s["start"] * 10) + 1, int(s["end"] * 10))]
            r = float(seg.mean()) / med if len(seg) else 1.0
            out.append(2 if r > 1.6 else 1 if r > 1.2 else 0)
        return out
    except Exception:
        return [None] * len(sents)


def plan(clip, out_dir=None, words=None, hook=True):
    info = probe(clip); dur = info["duration"]
    words = words if words is not None else load_words(clip)
    if not words:
        raise StudioError("no timestamped words for this clip (need <stem>.words.json, an SRT, or faster-whisper)")
    spans, st = pacing(words, dur, loud_gaps(clip) if info["has_audio"] else None)
    hook_pick = None
    if hook:
        sents = sentences(words)
        cands = []
        for s, ld in zip(sents, _loudness(clip, sents)):
            sc, why = score_hook(s, ld)
            cands.append({**s, "score": sc, "why": why})
        cands.sort(key=lambda c: -c["score"])
        if cands and cands[0]["score"] >= HOOK_MIN:
            hook_pick = cands[0]
    shots, t = [], 0.0
    if hook_pick:
        a, b = max(0.0, hook_pick["start"] - PAD), min(dur, hook_pick["end"] + PAD)
        shots.append({"role": "hook", "src_in": round(a, 3), "src_out": round(b, 3)})
    for a, b in spans:
        shots.append({"role": "body", "src_in": a, "src_out": b})
    for s in shots:
        s["out_in"] = round(t, 3); t += s["src_out"] - s["src_in"]; s["out_out"] = round(t, 3)
        s["text"] = " ".join(w["word"].strip() for w in words if w["start"] >= s["src_in"] - 0.01 and w["end"] <= s["src_out"] + 0.01)
    kept = sum(b - a for a, b in spans)
    stem = os.path.splitext(os.path.basename(clip))[0]; od = out_dir or os.path.dirname(os.path.abspath(clip))
    os.makedirs(od, exist_ok=True)
    cl = {"clip": os.path.abspath(clip), "rules": {"gap_max": GAP_MAX, "pad": PAD, "min_keep": MIN_KEEP, "hook_min": HOOK_MIN},
          "hook": hook_pick, "shots": shots,
          "stats": {"source_s": round(dur, 2), "body_s": round(kept, 2), "output_s": round(t, 2),
                    "dead_air_cut_s": round(dur - kept, 2), "tighter_pct": round(100 * (1 - kept / dur), 1) if dur else 0,
                    "fillers_cut": st["fillers"], "cuts": len(spans) - 1}}
    path = os.path.join(od, f"{stem}.cutlist.json"); json.dump(cl, open(path, "w"), indent=1)
    cl["cutlist"] = path; cl["storyboard"] = storyboard(clip, shots, os.path.join(od, f"{stem}.storyboard.jpg"))
    return cl


def storyboard(clip, shots, out, max_tiles=12):
    """one timecoded frame per shot, grid 4 wide; frame grabbed 30% into each shot"""
    from PIL import Image, ImageDraw, ImageFont
    tmp = out + ".frames"; os.makedirs(tmp, exist_ok=True); tiles = []
    for i, s in enumerate(shots[:max_tiles]):
        t = s["src_in"] + 0.3 * (s["src_out"] - s["src_in"]); f = os.path.join(tmp, f"{i:02d}.jpg")
        run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t:.3f}", "-i", clip, "-frames:v", "1", "-vf", "scale=-2:360", f])
        if os.path.exists(f): tiles.append((s, Image.open(f).convert("RGB")))
    if not tiles: return None
    tw = max(240, max(im.width for _, im in tiles)); th = 360 + 92; cols = min(4 if tw > 300 else 6, len(tiles)); rows = (len(tiles) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * (tw + 10) + 10, rows * (th + 10) + 10), (24, 24, 26)); d = ImageDraw.Draw(sheet)
    fb, fr = ImageFont.truetype(font("Bold"), 17), ImageFont.truetype(font("Medium"), 14)
    for i, (s, im) in enumerate(tiles):
        x, y = 10 + (i % cols) * (tw + 10), 10 + (i // cols) * (th + 10); sheet.paste(im, (x, y))
        col = (226, 38, 43) if s["role"] == "hook" else (238, 231, 214)
        d.text((x + 6, y + 364), f"{i + 1}. {s['role'].upper()}  {s['out_in']:.2f}-{s['out_out']:.2f}s", font=fb, fill=col)
        d.text((x + 6, y + 386), f"source {s['src_in']:.2f}-{s['src_out']:.2f}s", font=fr, fill=(150, 146, 138))
        txt = s["text"] or "—"; n = max(18, tw // 9)
        d.text((x + 6, y + 406), txt[:n], font=fr, fill=(200, 196, 188))
        if len(txt) > n: d.text((x + 6, y + 424), txt[n:2 * n - 1] + ("…" if len(txt) > 2 * n - 1 else ""), font=fr, fill=(200, 196, 188))
    sheet.save(out, quality=88)
    for f in os.listdir(tmp): os.remove(os.path.join(tmp, f))
    os.rmdir(tmp)
    return out


def _sig(cl): return hashlib.sha256(json.dumps(cl["shots"], sort_keys=True).encode()).hexdigest()[:16]


def approve(cutlist_path):
    cl = json.load(open(cutlist_path)); cl["approved"] = _sig(cl); json.dump(cl, open(cutlist_path, "w"), indent=1)
    return {"approved": cl["approved"], "cutlist": cutlist_path}


def render(cutlist_path, out, force=False):
    cl = json.load(open(cutlist_path))
    if not force and cl.get("approved") != _sig(cl):
        raise StudioError(f"cut list not approved (or edited after approval): review {cutlist_path} + storyboard, then approve")
    clip = cl["clip"]; info = probe(clip); shots = cl["shots"]; parts, labels = [], []
    for i, s in enumerate(shots):
        a, b = s["src_in"], s["src_out"]; d = b - a
        parts.append(f"[0:v]trim={a:.3f}:{b:.3f},setpts=PTS-STARTPTS[v{i}]")
        if info["has_audio"]:
            parts.append(f"[0:a]atrim={a:.3f}:{b:.3f},asetpts=PTS-STARTPTS,afade=t=in:d=0.012,afade=t=out:st={max(0, d - 0.012):.3f}:d=0.012[a{i}]")
            labels.append(f"[v{i}][a{i}]")
        else:
            labels.append(f"[v{i}]")
    n = len(shots); fg = ";".join(parts) + ";" + "".join(labels) + f"concat=n={n}:v=1:a={1 if info['has_audio'] else 0}[v]" + ("[a]" if info["has_audio"] else "")
    args = ["-i", clip, "-filter_complex", fg, "-map", "[v]"] + (["-map", "[a]"] + AUDIO_ENC if info["has_audio"] else []) + VIDEO_ENC
    ffmpeg(args, out)
    return {"out": out, "shots": n, "output_s": cl["stats"]["output_s"], "tighter_pct": cl["stats"]["tighter_pct"],
            "hook": (cl.get("hook") or {}).get("text")}


def make(clip, out, words=None, hook=False):
    """unattended (tier runs): plan + render in one go; the pipeline's own second-pass review is the approval"""
    words = words if words is not None else load_words(clip)
    if not words:                                   # gameplay with no speech: nothing to pace from, leave it alone
        return {"skipped": "no timestamped speech in this clip; pacing left as-is"}
    cl = plan(clip, os.path.dirname(os.path.abspath(out)), words=words, hook=hook)
    r = render(cl["cutlist"], out, force=True); r.update(storyboard=cl["storyboard"], cutlist=cl["cutlist"]); return r
