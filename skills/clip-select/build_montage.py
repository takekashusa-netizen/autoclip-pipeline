#!/usr/bin/env python3
"""
skills/clip-select/build_montage.py <script_json> <visual_json_or_empty>
    <montage_minutes> <montage_count> <out_path> [--padding SECONDS]

Packs the best available moments (transcript highlights + visual action
beats — same scoring as select.py) into a small number of LONG
highlight-reel clips, instead of one short clip per moment. Each output
"montage" is a list of source segments to be extracted and concatenated
into one continuous video — this is the actual "10-20 min video jam-packed
with exciting moments" feature, not just a longer single window.

Greedy fill: sort all candidate moments by score (best first), then for
each montage in turn, keep adding the next-best still-available,
non-overlapping moment until the montage reaches its target duration.
Moments are used at most once — a top highlight never gets reused across
two montages.
"""
import argparse
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


SAFETY_MARGIN_SEC = 2.0  # never extract right up to the literal end of a
                          # file — trailing corruption near the tail of a
                          # download is a real, recurring thing (hit this
                          # exact scenario with a real video), and an
                          # unclamped or exactly-at-duration end time can
                          # make ffmpeg hang indefinitely trying to seek
                          # into data that was never written, instead of
                          # erroring cleanly. A couple seconds of margin
                          # costs nothing and eliminates the whole failure
                          # class.


def is_mostly_loading_screen(start, end, visual_analysis, threshold=0.6):
    """Excludes a candidate whose time window is predominantly loading-
    screen/menu content — a highlight-scored transcript line or a motion
    spike that happens to land during a loading screen (rare, but does
    happen right as a match starts) shouldn't get selected as a clip
    just because of what's on screen at that exact moment being flat
    and static, not real gameplay."""
    if not visual_analysis:
        return False
    samples = [s for s in visual_analysis.get("samples", []) if start <= s["time"] < end]
    if not samples:
        return False
    loading_count = sum(1 for s in samples if s.get("is_loading_screen"))
    return (loading_count / len(samples)) >= threshold


def collect_candidates(kept_segments, visual_analysis, padding, duration, audio_analysis=None):
    """Each candidate is the beat's OWN interval (not a fixed-length window
    around it) — for a montage, we want the actual moment, padded a
    little for context, not an arbitrary clip_length slice.

    duration may be 0/missing from script.json (a real gap that existed in
    the silent-audio/no-audio fallback paths) — when that happens, fall
    back to visual_analysis's own duration (computed independently via
    OpenCV's frame_count/fps) rather than skipping clamping altogether."""
    effective_duration = duration or (visual_analysis or {}).get("duration") or 0
    safe_end_limit = max(0.0, effective_duration - SAFETY_MARGIN_SEC) if effective_duration else None

    def clamp_end(raw_end):
        if safe_end_limit is not None:
            return min(safe_end_limit, raw_end)
        return raw_end  # no duration info from ANY source — nothing to clamp against

    candidates = []
    for i, seg in enumerate(kept_segments):
        tags = classify(seg, i, is_first=(i == 0))
        s = score(tags)
        if s == 0:
            continue
        start = max(0.0, seg["start"] - padding)
        end = clamp_end(seg["end"] + padding)
        if end <= start:
            continue  # clamping pushed this entirely off the safe range — skip rather than emit a zero/negative-length segment
        if is_mostly_loading_screen(start, end, visual_analysis):
            continue
        candidates.append({"start": start, "end": end, "score": s, "text": seg["text"]})

    if visual_analysis:
        for beat in motion_beats(visual_analysis):
            start = max(0.0, beat["start"] - padding)
            end = clamp_end(beat["end"] + padding)
            if end <= start:
                continue
            if is_mostly_loading_screen(start, end, visual_analysis):
                continue
            candidates.append({"start": start, "end": end, "score": score(beat["tags"]),
                                "text": beat["text"]})

    if audio_analysis:
        for beat in transient_beats(audio_analysis):
            start = max(0.0, beat["start"] - padding)
            end = clamp_end(beat["end"] + padding)
            if end <= start:
                continue
            if is_mostly_loading_screen(start, end, visual_analysis):
                continue
            candidates.append({"start": start, "end": end, "score": score(beat["tags"]),
                                "text": beat["text"]})
    return candidates


def overlaps(a, b):
    return not (a["end"] <= b["start"] or a["start"] >= b["end"])


def build_montages(candidates, montage_seconds, montage_count):
    candidates = sorted(candidates, key=lambda c: (-c["score"], c["start"]))
    used = []  # segments already assigned to ANY montage — never reused
    montages = []

    for m_idx in range(montage_count):
        segments = []
        total = 0.0
        for c in candidates:
            if any(overlaps(c, s) for s in used):
                continue
            seg_len = c["end"] - c["start"]
            if total + seg_len > montage_seconds and segments:
                continue  # would overshoot and we already have something — skip, keep looking for a smaller fit
            segments.append(c)
            used.append(c)
            total += seg_len
            if total >= montage_seconds:
                break
        if not segments:
            break  # ran out of material — fewer montages than requested, not an error
        segments.sort(key=lambda s: s["start"])  # chronological order within the montage
        montages.append({
            "id": f"montage{m_idx+1:02d}",
            "segments": [{"start": s["start"], "end": s["end"], "text": s["text"], "score": s["score"]}
                         for s in segments],
            "total_duration": round(total, 2),
        })
    return montages


def main():
    p = argparse.ArgumentParser()
    p.add_argument("script_path")
    p.add_argument("visual_path")  # pass "" if none
    p.add_argument("montage_minutes", type=float)
    p.add_argument("montage_count", type=int)
    p.add_argument("out_path")
    p.add_argument("--padding", type=float, default=3.0)
    p.add_argument("--audio-path", default="")
    args = p.parse_args()

    script = json.load(open(args.script_path))
    visual_analysis = None
    if args.visual_path and os.path.exists(args.visual_path):
        try:
            data = json.load(open(args.visual_path))
            if "samples" in data:
                visual_analysis = data
        except Exception:
            pass

    audio_analysis = None
    if args.audio_path and os.path.exists(args.audio_path):
        try:
            data = json.load(open(args.audio_path))
            if "transients" in data:
                audio_analysis = data
        except Exception:
            pass

    has_transcript = script.get("transcription_available")
    if not has_transcript and not visual_analysis and not audio_analysis:
        json.dump({"montages": [], "note": "no transcript, visual, or audio analysis available"},
                   open(args.out_path, "w"), indent=2)
        print(json.dumps({"montage_count": 0}))
        return

    kept = script.get("kept_segments", []) if has_transcript else []
    duration = script.get("source_duration_sec", 0)

    candidates = collect_candidates(kept, visual_analysis, args.padding, duration, audio_analysis)
    montage_seconds = args.montage_minutes * 60
    montages = build_montages(candidates, montage_seconds, args.montage_count)

    json.dump({"montages": montages}, open(args.out_path, "w"), indent=2)
    print(json.dumps({
        "montage_count": len(montages),
        "segments_per_montage": [len(m["segments"]) for m in montages],
        "durations_sec": [m["total_duration"] for m in montages],
    }))


if __name__ == "__main__":
    main()
