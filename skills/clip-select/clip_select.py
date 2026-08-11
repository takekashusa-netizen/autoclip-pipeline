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
from audio_analysis import transient_beats  # noqa: E402

PRIORITY = {"impact": 4, "action": 3, "highlight": 3, "hook": 2, "stat": 1, "list_item": 1, "question": 1}


def score(tags):
    return max((PRIORITY.get(t, 0) for t in tags), default=0)


def is_mostly_loading_screen(start, end, visual_analysis, threshold=0.6):
    """Excludes a candidate whose time window is predominantly loading-
    screen/menu content — see build_montage.py's version of this, same
    logic, kept in sync."""
    if not visual_analysis:
        return False
    samples = [s for s in visual_analysis.get("samples", []) if start <= s["time"] < end]
    if not samples:
        return False
    loading_count = sum(1 for s in samples if s.get("is_loading_screen"))
    return (loading_count / len(samples)) >= threshold


def candidate_windows(kept_segments, clip_length, duration, visual_analysis=None, audio_analysis=None):
    """One candidate window per tagged beat, centered on that beat,
    clamped to source bounds. Transcript-based beats (highlight/hook/etc)
    plus, when visual_analysis is provided, motion-based 'action' beats —
    visual activity spikes independent of what was said, so a genuinely
    silent action moment (a fight, a big on-screen event) still gets
    picked up instead of only reacting to hype words in the transcript.
    Plus, when audio_analysis is provided, sharp-attack audio transients
    (gunfire/explosions/impacts) — a distinct signal from visual motion
    or transcript hype words. Any candidate landing mostly on a loading
    screen is dropped regardless of source."""
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
        if is_mostly_loading_screen(start, end, visual_analysis):
            continue
        candidates.append({"start": start, "end": end, "score": s, "text": seg["text"]})

    if visual_analysis:
        for beat in motion_beats(visual_analysis):
            mid = (beat["start"] + beat["end"]) / 2
            start = max(0.0, mid - clip_length / 2)
            end = min(duration, start + clip_length)
            start = max(0.0, end - clip_length)
            if is_mostly_loading_screen(start, end, visual_analysis):
                continue
            candidates.append({"start": start, "end": end, "score": score(beat["tags"]),
                                "text": beat["text"]})

    if audio_analysis:
        for beat in transient_beats(audio_analysis):
            mid = (beat["start"] + beat["end"]) / 2
            start = max(0.0, mid - clip_length / 2)
            end = min(duration, start + clip_length)
            start = max(0.0, end - clip_length)
            if is_mostly_loading_screen(start, end, visual_analysis):
                continue
            candidates.append({"start": start, "end": end, "score": score(beat["tags"]),
                                "text": beat["text"]})

    return candidates


def engagement_score(candidate, duration_sec=None):
    """A 0-100 heuristic engagement estimate, in the spirit of what
    'virality score' tools show — but honest about what it actually is:
    a weighted composite of signals we can actually measure (tag
    priority, word pace, text energy markers), NOT a trained model
    calibrated against real retention/engagement data. Treat it as a
    relative ranking aid between your own clips, not a prediction of
    real-world performance.
    """
    tags_component = min(60, (candidate["score"] / 4.0) * 60)  # 0-60 from tag priority

    text = candidate.get("text", "")
    words = text.split()
    word_count = len(words)

    pace_component = 0.0
    if duration_sec and duration_sec > 0 and word_count > 0:
        wps = word_count / duration_sec  # words per second — faster/punchier delivery
        pace_component = min(20, wps * 8)  # ~2.5 wps (conversational) -> ~20, caps there

    energy_markers = ["!", "?", "no way", "insane", "crazy", "clutch", "wow", "omg"]
    energy_hits = sum(1 for m in energy_markers if m in text.lower())
    energy_component = min(20, energy_hits * 7)

    total = tags_component + pace_component + energy_component
    return round(max(0, min(100, total)))


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
    audio_analysis_path = sys.argv[7] if len(sys.argv) > 7 else None

    script = json.load(open(script_path))

    visual_analysis = None
    if visual_analysis_path and os.path.exists(visual_analysis_path):
        try:
            data = json.load(open(visual_analysis_path))
            if "samples" in data:  # not an {"error": ...} fallback file
                visual_analysis = data
        except Exception:
            pass

    audio_analysis = None
    if audio_analysis_path and os.path.exists(audio_analysis_path):
        try:
            data = json.load(open(audio_analysis_path))
            if "transients" in data:
                audio_analysis = data
        except Exception:
            pass

    has_transcript = script.get("transcription_available")
    if not has_transcript and not visual_analysis and not audio_analysis:
        # real fix: this used to bail out completely whenever there was no
        # transcript, even when visual motion data COULD still pick good
        # clips (e.g. silent audio, or a transcription that failed) —
        # visual-only selection doesn't need a transcript at all, so only
        # give up when there's truly no signal of any kind
        json.dump({"clips": [], "note": "no transcript, visual, or audio analysis available — nothing to select from"},
                   open(out_path, "w"), indent=2)
        print(json.dumps({"clip_count": 0}))
        return

    kept = script.get("kept_segments", []) if has_transcript else []
    duration = script.get("source_duration_sec", 0)

    candidates = candidate_windows(kept, clip_length, duration, visual_analysis, audio_analysis)
    picked = pick_non_overlapping(candidates, clip_count, bonus_cap)

    clips = [
        {"id": f"clip{i+1:02d}", "start": c["start"], "end": c["end"],
         "score": c["score"], "bonus": c.get("bonus", False), "preview": c["text"][:80],
         "engagement_score": engagement_score(c, duration_sec=c["end"] - c["start"])}
        for i, c in enumerate(picked)
    ]
    bonus_count = sum(1 for c in clips if c["bonus"])
    json.dump({"clips": clips}, open(out_path, "w"), indent=2)
    print(json.dumps({"clip_count": len(clips), "bonus_count": bonus_count}))


if __name__ == "__main__":
    main()
