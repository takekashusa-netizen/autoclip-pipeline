#!/usr/bin/env python3
"""
skills/clip-select/select.py

Given a full transcript (rough-cut's script.json, already filler-removed)
and a target clip length, picks the K best non-overlapping windows to turn
into standalone clips — this is the actual "paste in a 4hr stream, get
clips out" feature.

Scoring priority: highlight (kills/clutch/hype) > hook (first line) >
stat/list_item > everything else. Ties broken by earlier-in-source first.
Reuses beat_planner's classify() so a beat tagged "highlight" here is the
same thing graphics-plan renders a card for later.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "graphics-plan"))
from beat_planner import classify  # noqa: E402
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "lib"))
from visual_analysis import motion_beats  # noqa: E402

PRIORITY = {"action": 3, "highlight": 3, "hook": 2, "stat": 1, "list_item": 1, "question": 1}


def score(tags):
    return max((PRIORITY.get(t, 0) for t in tags), default=0)


def candidate_windows(kept_segments, clip_length, duration, visual_analysis=None):
    """One candidate window per tagged beat, centered on that beat,
    clamped to source bounds. Transcript-based beats (highlight/hook/etc)
    plus, when visual_analysis is provided, motion-based 'action' beats —
    visual activity spikes independent of what was said, so a genuinely
    silent action moment (a fight, a big on-screen event) still gets
    picked up instead of only reacting to hype words in the transcript."""
    candidates = []
    for i, seg in enumerate(kept_segments):
        tags = classify(seg, i, is_first=(i == 0))
        s = score(tags)
        if s == 0:
            continue
        mid = (seg["start"] + seg["end"]) / 2
        start = max(0.0, mid - clip_length / 2)
        end = min(duration, start + clip_length)
        start = max(0.0, end - clip_length)  # re-clamp if end hit the ceiling
        candidates.append({"start": start, "end": end, "score": s, "text": seg["text"]})

    if visual_analysis:
        for beat in motion_beats(visual_analysis):
            mid = (beat["start"] + beat["end"]) / 2
            start = max(0.0, mid - clip_length / 2)
            end = min(duration, start + clip_length)
            start = max(0.0, end - clip_length)
            candidates.append({"start": start, "end": end, "score": score(beat["tags"]),
                                "text": beat["text"]})

    return candidates


HIGHLIGHT_SCORE = 3  # score() value when "highlight" tag is present — see PRIORITY

def pick_non_overlapping(candidates, count, bonus_cap=None):
    """Picks the top `count` non-overlapping windows, then — if bonus_cap
    is set — keeps grabbing additional pure-highlight (score==HIGHLIGHT_SCORE)
    windows beyond that count, since a strong kill/clutch/hype moment is
    worth clipping even if you only asked for N clips. Capped so a
    hype-heavy stream doesn't balloon into dozens of renders."""
    candidates.sort(key=lambda c: (-c["score"], c["start"]))
    picked = []
    for c in candidates:
        if any(not (c["end"] <= p["start"] or c["start"] >= p["end"]) for p in picked):
            continue
        picked.append(c)
        if len(picked) >= count:
            break

    if bonus_cap:
        for c in candidates:
            if len(picked) >= count + bonus_cap:
                break
            if c["score"] < HIGHLIGHT_SCORE:
                continue
            if any(not (c["end"] <= p["start"] or c["start"] >= p["end"]) for p in picked):
                continue
            c["bonus"] = True
            picked.append(c)

    picked.sort(key=lambda c: c["start"])
    return picked


def main():
    script_path, clip_length, clip_count, out_path = sys.argv[1:5]
    clip_length, clip_count = float(clip_length), int(clip_count)
    bonus_cap = int(sys.argv[5]) if len(sys.argv) > 5 else 0
    visual_analysis_path = sys.argv[6] if len(sys.argv) > 6 else None

    script = json.load(open(script_path))
    if not script.get("transcription_available"):
        json.dump({"clips": [], "note": "no transcript available — nothing to select from"},
                   open(out_path, "w"), indent=2)
        print(json.dumps({"clip_count": 0}))
        return

    kept = script.get("kept_segments", [])
    duration = script.get("source_duration_sec", 0)

    visual_analysis = None
    if visual_analysis_path and os.path.exists(visual_analysis_path):
        try:
            data = json.load(open(visual_analysis_path))
            if "samples" in data:  # not an {"error": ...} fallback file
                visual_analysis = data
        except Exception:
            pass

    candidates = candidate_windows(kept, clip_length, duration, visual_analysis)
    picked = pick_non_overlapping(candidates, clip_count, bonus_cap)

    clips = [
        {"id": f"clip{i+1:02d}", "start": c["start"], "end": c["end"],
         "score": c["score"], "bonus": c.get("bonus", False), "preview": c["text"][:80]}
        for i, c in enumerate(picked)
    ]
    bonus_count = sum(1 for c in clips if c["bonus"])
    json.dump({"clips": clips}, open(out_path, "w"), indent=2)
    print(json.dumps({"clip_count": len(clips), "bonus_count": bonus_count}))


if __name__ == "__main__":
    main()
