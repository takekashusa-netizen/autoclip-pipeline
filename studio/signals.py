"""Merge chat + game-event moments into one signals.json the clip selector reads.

Drop the file at projects/<job>/rough-cut/signals.json (studio.py signals
--job <job> does this) and skills/clip-select/clip_select.py will:
  * add up to +30 to any candidate window that contains a proven moment, and
  * add a candidate for any strong moment (score >= 60) the audio/visual pass missed.
Moments seen by BOTH chat and the HUD get a cross-confirmation bonus.

Times: detectors run on the source VOD. The rough cut can drop dead air,
so moments are mapped onto rough-cut time with the job's edl.json.
"""
import json
import os

MAX_BONUS = 30
INJECT_MIN = 60
CONFIRM_BONUS = 15


def merge(*moment_lists):
    allm = sorted((dict(m) for lst in moment_lists for m in (lst or [])), key=lambda m: m["start"])
    merged = []
    for m in allm:
        m.setdefault("sources", [m.get("source", "?")])
        if merged and m["start"] <= merged[-1]["end"]:
            cur = merged[-1]
            cur["end"] = max(cur["end"], m["end"])
            new_src = set(cur["sources"]) | set(m["sources"])
            confirmed = len(new_src) > 1 and len(set(cur["sources"])) == 1 and set(m["sources"]) != set(cur["sources"])
            cur["score"] = min(100, max(cur["score"], m["score"]) + (CONFIRM_BONUS if confirmed else 0))
            cur["sources"] = sorted(new_src)
            cur["label"] = f"{cur['label']} | {m['label']}"
            if m["score"] > cur.get("_best", 0):
                cur["peak_t"] = m.get("peak_t", cur.get("peak_t"))
            cur["_best"] = max(cur.get("_best", 0), m["score"])
        else:
            m["_best"] = m["score"]
            m["sources"] = sorted(set(m["sources"]))
            merged.append(m)
    for m in merged:
        m.pop("_best", None)
        if len(m["sources"]) > 1:
            m["confirmed"] = True
    return merged


def source_to_cut(t, keep):
    """Map a source-time second onto rough-cut time using EDL keep ranges.
    Returns None if t fell inside a removed stretch."""
    acc = 0.0
    for a, b in keep:
        if t < a:
            return None
        if t <= b:
            return acc + (t - a)
        acc += b - a
    return None


def map_to_cut(moments, edl_path):
    if not edl_path or not os.path.exists(edl_path):
        return moments
    keep = json.load(open(edl_path)).get("keep") or []
    if not keep:
        return moments
    out = []
    for m in moments:
        s = source_to_cut(m["start"], keep)
        e = source_to_cut(m["end"], keep)
        p = source_to_cut(m.get("peak_t", m["start"]), keep)
        if s is None and e is None and p is None:
            continue
        anchor = p if p is not None else (s if s is not None else e)
        span = m["end"] - m["start"]
        mm = dict(m)
        mm["start"] = round(s if s is not None else max(0.0, anchor - span / 2), 2)
        mm["end"] = round(e if e is not None else anchor + span / 2, 2)
        mm["peak_t"] = round(anchor, 2)
        mm["timebase"] = "rough_cut"
        out.append(mm)
    return out


def build(chat=None, game=None, edl_path=None):
    moments = merge((chat or {}).get("moments"), (game or {}).get("moments"))
    moments = map_to_cut(moments, edl_path)
    return {"version": 1, "moments": moments,
            "counts": {"chat": len((chat or {}).get("moments") or []), "game": len((game or {}).get("moments") or []),
                       "merged": len(moments)},
            "game_events": (game or {}).get("events", [])}


def save(signals, path):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    json.dump(signals, open(tmp, "w"), indent=2)
    os.replace(tmp, path)
    return path


class Signals:
    def __init__(self, data):
        self.moments = data.get("moments", [])

    @classmethod
    def load(cls, path):
        if not path or not os.path.exists(path):
            return None
        try:
            return cls(json.load(open(path)))
        except (ValueError, OSError):
            return None

    def bonus(self, start, end):
        """Bonus points + reasons for a candidate window [start, end]."""
        best, why = 0.0, []
        for m in self.moments:
            peak = m.get("peak_t", (m["start"] + m["end"]) / 2)
            if start <= peak <= end:
                b = m["score"] * 0.3 + (5 if m.get("confirmed") else 0)
            else:
                ov = min(end, m["end"]) - max(start, m["start"])
                if ov <= 0:
                    continue
                b = m["score"] * 0.3 * ov / max(1e-6, m["end"] - m["start"]) * 0.5
            if b > 0:
                why.append(m["label"])
            best = max(best, b)
        return int(round(min(MAX_BONUS, best))), why

    def strong(self, min_score=INJECT_MIN):
        return [m for m in self.moments if m["score"] >= min_score]


def window_for(moment, clip_length, duration, lead_in=4.0):
    """A clip_length window that contains the moment's lead-up and its peak."""
    peak = moment.get("peak_t", moment["end"])
    start = max(0.0, min(moment["start"] - lead_in, peak - clip_length * 0.7))
    end = start + clip_length
    if duration and end > duration:
        end = duration
        start = max(0.0, end - clip_length)
    return round(start, 2), round(end, 2)
