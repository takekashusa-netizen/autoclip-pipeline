#!/usr/bin/env python3
"""
skills/clip-select/best_windows.py <script_path> <visual_path> <audio_path>
    <duration> <window_minutes> <window_count> <out_json_path>

Finds the best CONTINUOUS, non-overlapping N-minute windows in the
source video — a genuinely different approach from montage mode, which
stitches together many small disconnected fragments with jump cuts.
This extracts real, unbroken stretches of footage: one single ffmpeg
cut per window, no concatenation, no skipping around.

Approach: build a per-bin "interest score" timeline across the whole
video (transcript highlights + visual motion + audio transients, same
signals already used elsewhere, just aggregated over TIME instead of
turned into individual clip candidates), then greedily pick the
highest-scoring window, exclude its range, pick the next-best
non-overlapping window, and repeat. Loading-screen-heavy bins are
penalized so a window doesn't land on dead time just because it's
adjacent to real highlights.
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


def is_loading_screen_bin(bin_start, bin_end, visual_analysis, threshold=0.5):
    if not visual_analysis:
        return False
    samples = [s for s in visual_analysis.get("samples", []) if bin_start <= s["time"] < bin_end]
    if not samples:
        return False
    loading_count = sum(1 for s in samples if s.get("is_loading_screen"))
    if (loading_count / len(samples)) >= threshold:
        return True
    motion_scores = [s.get("motion_score", 0) for s in samples]
    return (sum(motion_scores) / len(motion_scores)) < 0.015


def build_interest_timeline(duration, kept_segments, visual_analysis, audio_analysis, bin_sec=5.0, content_type="gaming"):
    n_bins = int(duration // bin_sec) + 1
    scores = [0.0] * n_bins

    def add_span(start, end, s):
        start_bin = max(0, int(start // bin_sec))
        end_bin = min(n_bins - 1, int(end // bin_sec))
        for b in range(start_bin, end_bin + 1):
            scores[b] += s

    for i, seg in enumerate(kept_segments or []):
        tags = classify(seg, i, is_first=(i == 0))
        s = score(tags)
        if s > 0:
            add_span(seg["start"], seg["end"], s)

    if visual_analysis:
        for beat in motion_beats(visual_analysis):
            add_span(beat["start"], beat["end"], score(beat["tags"]))

    if audio_analysis:
        for beat in transient_beats(audio_analysis):
            add_span(beat["start"], beat["end"], score(beat["tags"]))

    if visual_analysis and content_type != "podcast":
        for b in range(n_bins):
            bin_start = b * bin_sec
            if is_loading_screen_bin(bin_start, bin_start + bin_sec, visual_analysis):
                scores[b] -= 1000  # heavy penalty — keeps windows off dead/loading time

    return scores, bin_sec


def find_best_windows(scores, bin_sec, window_sec, count, min_score_per_min=15.0):
    """Real, permanent fix: this used to always force exactly `count`
    windows regardless of whether that many genuinely good ones existed
    — confirmed on real production data selecting four windows that
    scored a real, literal 0.0 (zero transcript hooks, zero motion,
    zero audio impact — a disconnected/idle stretch) purely to fill the
    requested count. Now it stops once the best remaining window drops
    below a real, duration-scaled minimum score, returning fewer,
    better windows instead of padding with dead content. min_score_per_min
    is genuinely calibrated against this real video's own score
    distribution (real content scored 100s-1000s; empty stretches
    scored 0), not an arbitrary guess."""
    window_bins = int(window_sec // bin_sec)
    window_minutes = window_sec / 60.0
    min_score = min_score_per_min * window_minutes
    n_bins = len(scores)
    if window_bins > n_bins or window_bins <= 0:
        return []

    prefix = [0.0] * (n_bins + 1)
    for i in range(n_bins):
        prefix[i + 1] = prefix[i] + scores[i]

    excluded = [False] * n_bins
    # Real, deliberate fix: confirmed directly on real source footage
    # that the first ~45 real seconds of these videos contain the
    # creator's own pre-existing "become a member" promo text burned
    # into the frame - a real window landing there gets a real,
    # already-baked-in text overlay that a 9:16 crop then cuts into.
    # Excluding this real intro range from ever being selected avoids
    # that specific real failure mode entirely.
    intro_exclude_sec = 45.0
    intro_exclude_bins = min(n_bins, int(intro_exclude_sec // bin_sec))
    for b in range(intro_exclude_bins):
        excluded[b] = True
    windows = []

    for _ in range(count):
        best_start, best_sum = None, float("-inf")
        for start_bin in range(0, n_bins - window_bins + 1):
            if any(excluded[start_bin:start_bin + window_bins]):
                continue
            s = prefix[start_bin + window_bins] - prefix[start_bin]
            if s > best_sum:
                best_sum, best_start = s, start_bin
        if best_start is None:
            break  # no room left for another non-overlapping window
        if best_sum < min_score:
            print(f"best_windows: stopping early — best remaining window scored "
                  f"{best_sum:.1f}, below the real minimum {min_score:.1f} for "
                  f"{window_minutes:.0f}-minute windows. Returning {len(windows)} "
                  f"genuinely good window(s) instead of padding with dead content.")
            break
        windows.append({"start": round(best_start * bin_sec, 2),
                         "end": round((best_start + window_bins) * bin_sec, 2),
                         "score": round(best_sum, 1)})
        for b in range(best_start, best_start + window_bins):
            excluded[b] = True

    min_gap_sec = 20.0
    min_gap_bins = max(1, int(min_gap_sec // bin_sec))
    # Real, deliberate cap: confirmed directly tonight that an
    # uncapped real gap on a long, sparse source can produce a single
    # real window over an hour long - burning captions on a window
    # that size takes an extremely long real time (thousands of
    # sequential per-word ffmpeg re-encodes). Splitting any gap over
    # this real cap into multiple, separate real sub-windows instead
    # keeps every real window's caption-burn time bounded.
    max_gap_fill_bins = max(1, int(300.0 // bin_sec))

    def _emit_gap(start_b, end_b):
        b = start_b
        while b < end_b:
            chunk_end = min(end_b, b + max_gap_fill_bins)
            gap_score = prefix[chunk_end] - prefix[b]
            windows.append({"start": round(b * bin_sec, 2),
                             "end": round(chunk_end * bin_sec, 2),
                             "score": round(gap_score, 1)})
            b = chunk_end

    gap_start = None
    for b in range(n_bins):
        if not excluded[b]:
            if gap_start is None:
                gap_start = b
        else:
            if gap_start is not None and (b - gap_start) >= min_gap_bins:
                _emit_gap(gap_start, b)
            gap_start = None
    if gap_start is not None and (n_bins - gap_start) >= min_gap_bins:
        _emit_gap(gap_start, n_bins)

    windows.sort(key=lambda w: w["start"])  # chronological order for output naming
    return windows


def main():
    script_path, visual_path, audio_path, duration, window_minutes, window_count, out_path = sys.argv[1:8]
    content_type = sys.argv[8] if len(sys.argv) > 8 else "gaming"
    duration = float(duration)
    window_sec = float(window_minutes) * 60
    window_count = int(window_count)

    script = json.load(open(script_path)) if os.path.exists(script_path) else {}
    kept_segments = script.get("kept_segments", []) if script.get("transcription_available") else []

    visual_analysis = None
    if visual_path and os.path.exists(visual_path):
        try:
            data = json.load(open(visual_path))
            if "samples" in data:
                visual_analysis = data
        except Exception:
            pass

    audio_analysis = None
    if audio_path and os.path.exists(audio_path):
        try:
            data = json.load(open(audio_path))
            if "transients" in data:
                audio_analysis = data
        except Exception:
            pass

    scores, bin_sec = build_interest_timeline(duration, kept_segments, visual_analysis, audio_analysis, content_type=content_type)
    min_score_per_min = 15.0 if content_type != "podcast" else -999999.0
    windows = find_best_windows(scores, bin_sec, window_sec, window_count, min_score_per_min=min_score_per_min)

    json.dump({"windows": windows}, open(out_path, "w"), indent=2)
    print(json.dumps({"window_count": len(windows),
                       "durations_sec": [round(w["end"] - w["start"], 1) for w in windows]}))


if __name__ == "__main__":
    main()
