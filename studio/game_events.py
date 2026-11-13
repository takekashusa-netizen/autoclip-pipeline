"""Game-event detection: read the HUD (kill feed, banners, scoreboard) with OCR.

Samples the video (default 1 frame/s), crops each game's HUD regions,
cleans them up, and OCRs them in one batched tesseract call per region
(one process for thousands of crops, not one per frame). Text is matched
against per-game patterns to emit events: kills, knocks, squad wipes,
wins, and for 2K, score jumps (threes, and-ones, game-winners).

Region boxes are fractions of the frame (x0, y0, x1, y1) and are defaults
for 1080p/16:9 captures — calibrate per creator with --region if their HUD
layout or overlay differs (studio.py game-events --dump-crops shows exactly
what the OCR sees).
"""
import json
import os
import re
import shutil
import subprocess
import tempfile

from .common import StudioError, probe

PROFILES = {
    "apex": {
        "regions": {"feed": (0.60, 0.03, 0.995, 0.24), "banner": (0.22, 0.10, 0.78, 0.40)},
        "patterns": [
            ("banner", r"\bCHAMPION", "win", 40),
            ("banner", r"SQUAD\s+(ELIMINATED|WIPED)", "squad_wipe", 28),
            ("banner", r"\bKNOCK(ED)?\b", "knock", 6),
            ("banner", r"\bELIMINATED\b", "kill", 10),
            ("feed", None, "kill", 10),           # player-name kill-feed lines
        ],
    },
    "warzone": {
        "regions": {"feed": (0.0, 0.50, 0.36, 0.82), "banner": (0.22, 0.10, 0.78, 0.42)},
        "patterns": [
            ("banner", r"(WARZONE\s+)?VICTORY|YOU\s+WON|WINNERS?\b", "win", 40),
            ("banner", r"SQUAD\s+WIPE", "squad_wipe", 28),
            ("banner", r"\bDOWNED\b|ENEMY\s+DOWN", "knock", 6),
            ("banner", r"ELIMINATION|ENEMY\s+KILLED|\bKILLED\b", "kill", 10),
            ("feed", None, "kill", 10),
        ],
    },
    "nba2k": {
        "regions": {"score": (0.20, 0.86, 0.80, 0.995), "banner": (0.20, 0.25, 0.80, 0.60)},
        "patterns": [
            ("banner", r"AND[\s\-]*(ONE|1)\b", "and_one", 15),
            ("banner", r"GAME[\s\-]*WINNER|BUZZER", "game_winner", 40),
            ("banner", r"\bPOSTER(IZED)?\b|\bDUNK\b", "dunk", 12),
            ("banner", r"\bFINAL\b", "game_end", 8),
            ("score", None, "score_jump", 0),     # handled numerically
        ],
    },
    "generic": {
        "regions": {"banner": (0.20, 0.10, 0.80, 0.45)},
        "patterns": [
            ("banner", r"VICTORY|CHAMPION|YOU\s+WIN|WINNER", "win", 40),
            ("banner", r"SQUAD\s+(WIPE|WIPED|ELIMINATED)|ACE\b|TEAM\s+WIPE", "squad_wipe", 28),
            ("banner", r"HEADSHOT", "headshot", 8),
            ("banner", r"ELIMINATED|KILLED", "kill", 10),
            ("banner", r"KNOCK(ED)?|DOWNED", "knock", 6),
        ],
    },
}
WEIGHT = {"win": 40, "game_winner": 40, "squad_wipe": 28, "and_one": 15, "dunk": 12, "kill": 10,
          "headshot": 8, "three": 8, "game_end": 8, "knock": 6}


def _need_tesseract():
    if not shutil.which("tesseract"):
        raise StudioError("tesseract not installed — Mac: brew install tesseract")


def _frames(video, fps, width=1280):
    """Yield (t, BGR ndarray) for each sampled frame via a single ffmpeg pipe."""
    import numpy as np
    info = probe(video)
    h = int(round(info["height"] * width / info["width"] / 2) * 2)
    cmd = ["ffmpeg", "-v", "error", "-i", video, "-vf", f"fps={fps},scale={width}:{h}", "-f", "rawvideo",
           "-pix_fmt", "bgr24", "-"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stdin=subprocess.DEVNULL)
    size = width * h * 3
    i = 0
    try:
        while True:
            buf = p.stdout.read(size)
            if len(buf) < size:
                break
            yield i / fps, np.frombuffer(buf, np.uint8).reshape(h, width, 3)
            i += 1
    finally:
        p.stdout.close()
        p.wait()


def _prep(crop):
    """Grayscale, 2x upscale, Otsu threshold; invert so text is dark on light (tesseract's best case)."""
    import cv2
    import numpy as np
    g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    # coloured HUD text (red/yellow/white) — take max channel so it all goes bright
    g = np.maximum(g, crop.max(axis=2))
    g = cv2.resize(g, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    _, th = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    if th.mean() < 127:
        th = 255 - th
    return th


def _ocr_batch(paths, psm=6):
    """OCR many images in one tesseract run; returns one text per image."""
    if not paths:
        return []
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as lf:
        lf.write("\n".join(paths))
        lst = lf.name
    try:
        r = subprocess.run(["tesseract", lst, "stdout", "--psm", str(psm), "-l", "eng"], capture_output=True,
                           text=True, timeout=7200, stdin=subprocess.DEVNULL)
    finally:
        os.remove(lst)
    if r.returncode != 0:
        raise StudioError(f"tesseract failed: {r.stderr[-400:]}")
    pages = r.stdout.split("\f")
    pages = (pages + [""] * len(paths))[: len(paths)]
    return pages


def _norm(s):
    """Uppercase, collapse spaces inside each line, keep line breaks (kill feeds are line-based)."""
    lines = [re.sub(r"[ \t]+", " ", l).strip() for l in s.upper().splitlines()]
    return "\n".join(l for l in lines if l)


def scan(video, game="generic", fps=1.0, player=None, regions=None, dump_dir=None, chunk=600):
    """OCR the HUD and return raw per-sample text per region."""
    import cv2
    _need_tesseract()
    prof = PROFILES.get(game) or PROFILES["generic"]
    regs = dict(prof["regions"])
    if regions:
        regs.update(regions)
    work = dump_dir or tempfile.mkdtemp(prefix="gev_")
    os.makedirs(work, exist_ok=True)
    texts = {r: [] for r in regs}
    times = []
    pending = {r: [] for r in regs}

    def flush():
        for r in regs:
            texts[r].extend(_ocr_batch(pending[r]))
            if not dump_dir:
                for p in pending[r]:
                    os.remove(p)
            pending[r] = []

    for t, frame in _frames(video, fps):
        h, w = frame.shape[:2]
        times.append(t)
        for r, (x0, y0, x1, y1) in regs.items():
            crop = frame[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)]
            p = os.path.join(work, f"{r}_{len(times):06d}.png")
            cv2.imwrite(p, _prep(crop))
            pending[r].append(p)
        if len(times) % chunk == 0:
            flush()
    flush()
    if not dump_dir:
        shutil.rmtree(work, ignore_errors=True)
    return {"times": times, "texts": {r: [_norm(x) for x in v] for r, v in texts.items()}, "game": game,
            "player": player}


def events_from_scan(sc, player=None):
    game = sc["game"]
    prof = PROFILES.get(game) or PROFILES["generic"]
    times, texts = sc["times"], sc["texts"]
    player = (player or sc.get("player") or "").upper()
    raw = []  # (t, type, from_feed)
    for region, pat, etype, _ in prof["patterns"]:
        if region not in texts or pat is not None:
            continue
        if region == "feed" and player:
            from collections import Counter
            prev = Counter()
            for t, txt in zip(times, texts[region]):
                now = Counter(l.strip() for l in txt.split("\n") if player in l.replace(" ", "") or player in l)
                # a line credited to the player that wasn't there last sample = a new kill
                for _ in range(sum((now - prev).values())):
                    raw.append((t, "kill", True))
                prev = now
        elif region == "score":
            prev = None
            for t, txt in zip(times, texts[region]):
                nums = [int(n) for n in re.findall(r"\b(\d{1,3})\b", txt)]
                if len(nums) >= 2:
                    pair = (nums[0], nums[-1])
                    if prev and any(b - a == 3 for a, b in zip(prev, pair)):
                        raw.append((t, "three", True))
                    prev = pair
    # text patterns: per region and sample, only the FIRST (strongest) matching rule counts,
    # so "SQUAD ELIMINATED" is a squad wipe, not also a kill
    by_region = {}
    for region, pat, etype, _ in prof["patterns"]:
        if pat is not None and region in texts:
            by_region.setdefault(region, []).append((re.compile(pat), etype))
    for region, rules in by_region.items():
        for t, txt in zip(times, texts[region]):
            flat = txt.replace("\n", " ")
            for rx, etype in rules:
                if rx.search(flat):
                    raw.append((t, etype, False))
                    break
    # banners stay on screen for seconds: collapse repeats of the same type within 4 s
    raw.sort()
    events = []
    last = {}
    for t, et, from_feed in raw:
        if not from_feed and et in last and t - last[et] <= 4.0:
            last[et] = t
            continue
        if not from_feed:
            last[et] = t
        events.append({"t": round(t, 2), "type": et, "weight": WEIGHT.get(et, 5)})
    dedup = events
    return dedup


def to_moments(events, lead=10.0, after=4.0, combo_gap=10.0):
    """Group events into moments; 2+ kills inside combo_gap becomes a multi-kill."""
    moments = []
    for e in sorted(events, key=lambda e: e["t"]):
        if moments and e["t"] - moments[-1]["_last"] <= combo_gap:
            m = moments[-1]
            m["events"].append(e)
            m["_last"] = e["t"]
        else:
            moments.append({"events": [e], "_first": e["t"], "_last": e["t"]})
    out = []
    for m in moments:
        kills = sum(1 for e in m["events"] if e["type"] == "kill")
        types = [e["type"] for e in m["events"]]
        score = sum(e["weight"] for e in m["events"])
        label = ", ".join(sorted(set(types)))
        if kills >= 2:
            score += (kills - 1) * 10
            rest = sorted(set(types) - {"kill"})
            label = f"{kills}-kill streak" + (f" + {', '.join(rest)}" if rest else "")
        out.append({"start": round(max(0.0, m["_first"] - lead), 2), "end": round(m["_last"] + after, 2),
                    "peak_t": m["_last"], "score": min(100, score), "events": m["events"], "kills": kills,
                    "source": "game", "label": label})
    out.sort(key=lambda m: -m["score"])
    return out


def detect(video, game="generic", player=None, fps=1.0, regions=None, dump_dir=None):
    sc = scan(video, game=game, fps=fps, player=player, regions=regions, dump_dir=dump_dir)
    ev = events_from_scan(sc, player)
    return {"game": game, "samples": len(sc["times"]), "events": ev, "moments": to_moments(ev)}


def parse_region(spec):
    """'feed=0.6,0.03,0.99,0.24' -> ('feed', (..))"""
    name, vals = spec.split("=", 1)
    box = tuple(float(v) for v in vals.split(","))
    if len(box) != 4 or not all(0 <= v <= 1 for v in box):
        raise StudioError(f"bad region {spec}: need name=x0,y0,x1,y1 as 0-1 fractions")
    return name, box


if __name__ == "__main__":
    import sys
    print(json.dumps(detect(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "generic"), indent=2))
