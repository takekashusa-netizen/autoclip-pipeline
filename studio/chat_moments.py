"""Chat-proven moments: find the seconds where chat actually exploded.

Input: a chat log from any of
  - JSON list / JSONL of {"t"|"time"|"offset": seconds, "user", "text"|"message"}
  - yt-dlp live_chat.json (YouTube live replays)  — fetched with fetch_chat(url)
  - plain text lines "[HH:MM:SS] user: message" (offsets from stream start)

Detection: messages are binned (5 s). Each bin is tested against the stream's
own baseline rate with a Poisson tail test, Bonferroni-corrected for the
number of bins — so a 4-hour stream doesn't "find" spikes by chance. Hype
words (CLIP, NO WAY, W, LMAO, emotes...) add weight. Chat reacts after the
play, so each moment's window reaches back `react_lag` seconds.
"""
import glob
import json
import math
import os
import re
import subprocess
import tempfile

from .common import StudioError

BIN = 5.0
HYPE = {
    "clip": 3.0, "clip it": 4.0, "clip that": 4.0, "no way": 2.5, "nah": 1.0, "w": 1.5, "dub": 1.5,
    "lmao": 1.5, "lol": 1.0, "omg": 2.0, "insane": 2.0, "crazy": 1.5, "clutch": 2.5, "goat": 2.0,
    "pog": 2.0, "poggers": 2.0, "kekw": 1.5, "lul": 1.0, "holy": 1.5, "yooo": 2.0, "sheesh": 2.0,
    "run it back": 2.5, "what": 0.8, "how": 0.8, "?": 0.3, "!": 0.3,
}


def _parse_hms(s):
    parts = [int(p) for p in s.split(":")]
    while len(parts) < 3:
        parts.insert(0, 0)
    return parts[0] * 3600 + parts[1] * 60 + parts[2]


def load_chat(path):
    """Return [{'t': float_sec, 'user': str, 'text': str}] sorted by t."""
    raw = open(path, encoding="utf-8", errors="ignore").read()
    msgs = []
    stripped = raw.lstrip()
    items = None
    if stripped.startswith("["):
        try:
            items = json.loads(stripped)
        except json.JSONDecodeError:
            items = None
    if items is None and stripped.startswith("{"):
        items = []
        for line in raw.splitlines():
            line = line.strip()
            if line:
                try:
                    items.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    if items is not None:
        for it in items:
            m = _from_obj(it)
            if m:
                msgs.append(m)
    else:
        rx = re.compile(r"^\[?(\d{1,2}:\d{2}(?::\d{2})?)\]?\s+([^:]{1,40}):\s?(.*)$")
        for line in raw.splitlines():
            mm = rx.match(line.strip())
            if mm:
                msgs.append({"t": float(_parse_hms(mm.group(1))), "user": mm.group(2).strip(), "text": mm.group(3)})
    msgs.sort(key=lambda m: m["t"])
    return msgs


def _from_obj(it):
    if not isinstance(it, dict):
        return None
    # yt-dlp live_chat.json line
    if "replayChatItemAction" in it:
        rca = it["replayChatItemAction"]
        off = float(rca.get("videoOffsetTimeMsec", 0)) / 1000
        for act in rca.get("actions", []):
            item = act.get("addChatItemAction", {}).get("item", {})
            r = item.get("liveChatTextMessageRenderer") or item.get("liveChatPaidMessageRenderer")
            if not r:
                continue
            text = "".join(run.get("text", "") or (":" + run.get("emoji", {}).get("shortcuts", [""])[0].strip(":") + ":")
                           for run in r.get("message", {}).get("runs", []))
            user = r.get("authorName", {}).get("simpleText", "")
            return {"t": off, "user": user, "text": text}
        return None
    for k in ("t", "time", "offset", "content_offset_seconds", "timestamp_sec"):
        if k in it:
            try:
                t = float(it[k])
            except (TypeError, ValueError):
                continue
            text = it.get("text") or it.get("message") or it.get("body") or ""
            if isinstance(text, dict):
                text = text.get("body", "")
            user = it.get("user") or it.get("name") or it.get("author") or ""
            if isinstance(user, dict):
                user = user.get("display_name", "")
            return {"t": t, "user": str(user), "text": str(text)}
    return None


def fetch_chat(url, out_dir):
    """Download a chat replay with yt-dlp. Works for YouTube live replays
    (live_chat). Twitch VOD chat is attempted via yt-dlp's rechat track; if
    Twitch returns nothing, record chat live with the stream logger instead."""
    os.makedirs(out_dir, exist_ok=True)
    cmd = ["yt-dlp", "--skip-download", "--write-subs", "--sub-langs", "live_chat,rechat",
           "-o", os.path.join(out_dir, "chat.%(ext)s"), url]
    try:
        subprocess.run(cmd, capture_output=True, text=True, timeout=1800, stdin=subprocess.DEVNULL)
    except FileNotFoundError as e:
        raise StudioError("yt-dlp not installed (pip install yt-dlp)") from e
    found = sorted(glob.glob(os.path.join(out_dir, "chat*.json")))
    if not found:
        raise StudioError("no chat replay available for this URL — for Twitch, log chat live during the stream "
                          "and pass the log file with --chat")
    return found[0]


def _poisson_sf(k, lam):
    """P(X >= k) for Poisson(lam), computed stably in log space."""
    if k <= 0:
        return 1.0
    if lam <= 0:
        return 0.0
    # sum pmf from k upward until negligible
    logp = -lam + k * math.log(lam) - math.lgamma(k + 1)
    total = 0.0
    i = k
    while True:
        p = math.exp(logp)
        total += p
        i += 1
        logp += math.log(lam) - math.log(i)
        if p < 1e-16 * max(total, 1e-300) or i > k + 10000:
            break
    return min(1.0, total)


def hype_weight(text):
    t = " " + re.sub(r"\s+", " ", text.lower()) + " "
    w = 0.0
    for k, v in HYPE.items():
        if k in "?!":
            w += min(3, t.count(k)) * v
        elif f" {k} " in t or (len(k) > 3 and k in t):
            w += v
    if len(text) > 3 and text.isupper():
        w += 1.0
    return w


def detect(msgs, react_lag=12.0, after=4.0, alpha=0.01, min_msgs=6):
    """Return chat moments sorted by score (0-100)."""
    if not msgs:
        return {"moments": [], "baseline_per_bin": 0, "bins": 0, "messages": 0}
    end = msgs[-1]["t"]
    nb = int(end // BIN) + 1
    counts = [0] * nb
    hype = [0.0] * nb
    users = [set() for _ in range(nb)]
    for m in msgs:
        i = int(m["t"] // BIN)
        counts[i] += 1
        hype[i] += hype_weight(m["text"])
        users[i].add(m["user"])
    # baseline: median of a +-10 minute neighbourhood, so a busy late stream
    # isn't compared against a quiet start.
    half = int(600 / BIN)
    thr = alpha / max(1, nb)
    hits = []
    for i in range(nb):
        lo, hi = max(0, i - half), min(nb, i + half + 1)
        neigh = sorted(counts[lo:hi])
        base = max(0.5, neigh[len(neigh) // 2])
        if counts[i] < min_msgs:
            continue
        p = _poisson_sf(counts[i], base)
        if p < thr:
            hits.append((i, counts[i], base, p))
    # merge adjacent bins into moments
    moments = []
    for i, c, base, p in hits:
        if moments and i - moments[-1]["_last"] <= 2:
            mo = moments[-1]
            mo["_last"] = i
            mo["msgs"] += c
            mo["peak_ratio"] = max(mo["peak_ratio"], c / base)
            mo["min_p"] = min(mo["min_p"], p)
            mo["hype"] += hype[i]
            mo["chatters"] |= users[i]
            if c > mo["_peakc"]:
                mo["_peakc"], mo["peak_t"] = c, i * BIN + BIN / 2
        else:
            moments.append({"_first": i, "_last": i, "_peakc": c, "peak_t": i * BIN + BIN / 2, "msgs": c,
                            "peak_ratio": c / base, "min_p": p, "hype": hype[i], "chatters": set(users[i])})
    out = []
    for mo in moments:
        first_t = mo["_first"] * BIN
        last_t = (mo["_last"] + 1) * BIN
        sig = min(40.0, -math.log10(max(mo["min_p"], 1e-300)) * 4)
        ratio = min(25.0, (mo["peak_ratio"] - 1) * 5)
        hy = min(25.0, mo["hype"] / max(1, mo["msgs"]) * 12)
        breadth = min(10.0, len(mo["chatters"]) / 2)
        score = round(min(100.0, sig + ratio + hy + breadth))
        out.append({
            "start": round(max(0.0, first_t - react_lag), 2), "end": round(last_t + after, 2),
            "peak_t": mo["peak_t"], "messages": mo["msgs"], "chatters": len(mo["chatters"]),
            "rate_x_baseline": round(mo["peak_ratio"], 2), "p_value": float(f"{mo['min_p']:.3g}"),
            "hype_per_msg": round(mo["hype"] / max(1, mo["msgs"]), 2), "score": score, "source": "chat",
            "label": f"chat spike x{mo['peak_ratio']:.1f} ({mo['msgs']} msgs)",
        })
    out.sort(key=lambda m: -m["score"])
    return {"moments": out, "messages": len(msgs), "bins": nb}


def detect_file(path, **kw):
    return detect(load_chat(path), **kw)


def fetch_and_detect(url, **kw):
    d = tempfile.mkdtemp(prefix="chat_")
    return detect_file(fetch_chat(url, d), **kw)
