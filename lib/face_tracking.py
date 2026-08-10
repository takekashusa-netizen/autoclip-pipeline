#!/usr/bin/env python3
"""
lib/face_tracking.py

Turns visual_analysis.py's sparse face_center samples into a small number
of per-segment crop targets — the actual completion of the face-tracking
feature (detection existed, nothing used it for reframing until now).

Deliberately segment-based, not continuous per-frame tracking: a fully
animated crop path would need a long ffmpeg expression evaluated every
frame, and we already hit a real ffmpeg crash tonight from an
overly-long generated expression (a different feature, same lesson).
Splitting into a handful of segments, each with ONE static crop position
(the average face location across that segment), avoids that risk
entirely and is still a real, visible improvement over a single
whole-video center crop — the frame follows the speaker across scene/
position changes, just not smoothly within one continuous shot.
"""
import json
import sys


def compute_segments(analysis, segment_sec=8.0, min_samples_with_face=2):
    """Returns [{"start":.., "end":.., "center_x":.., "center_y":..}, ...]
    covering the full video duration. Segments with no (or too few) face
    detections fall back to center (0.5, 0.5) — i.e. today's existing
    center-crop behavior for that stretch, never a wild/wrong guess."""
    duration = analysis.get("duration", 0)
    samples = analysis.get("samples", [])
    if not duration or not samples:
        return []

    segments = []
    t = 0.0
    while t < duration:
        seg_end = min(duration, t + segment_sec)
        in_window = [s for s in samples
                     if t <= s["time"] < seg_end and s.get("face_center")]
        if len(in_window) >= min_samples_with_face:
            cx = sum(s["face_center"][0] for s in in_window) / len(in_window)
            cy = sum(s["face_center"][1] for s in in_window) / len(in_window)
        else:
            cx, cy = 0.5, 0.5  # not enough signal — fall back to center
        segments.append({"start": t, "end": seg_end, "center_x": round(cx, 4), "center_y": round(cy, 4)})
        t = seg_end
    return segments


def has_real_face_data(analysis, min_fraction=0.05):
    """Whether this video has ANY meaningful amount of face detection —
    below this, face-tracking crop isn't worth the extra render pass over
    the existing static center-crop (e.g. a gameplay video with no
    webcam facecam, or a cascade that never fired)."""
    samples = analysis.get("samples", [])
    if not samples:
        return False
    with_face = sum(1 for s in samples if s.get("face_center"))
    return (with_face / len(samples)) >= min_fraction


def main():
    analysis_path, out_path = sys.argv[1], sys.argv[2]
    segment_sec = float(sys.argv[3]) if len(sys.argv) > 3 else 8.0

    analysis = json.load(open(analysis_path))
    if not has_real_face_data(analysis):
        json.dump({"segments": [], "note": "insufficient face detection data — not worth face-tracking crop"},
                   open(out_path, "w"), indent=2)
        print(json.dumps({"usable": False}))
        return

    segments = compute_segments(analysis, segment_sec)
    json.dump({"segments": segments}, open(out_path, "w"), indent=2)
    print(json.dumps({"usable": True, "segment_count": len(segments)}))


if __name__ == "__main__":
    main()
