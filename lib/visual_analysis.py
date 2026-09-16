#!/usr/bin/env python3
"""
lib/visual_analysis.py <video_path> <out_json_path> [--interval SECONDS]

Samples frames sparsely (not full framerate — that would be far too slow
for a multi-hour video) and for each sample:
  - runs face detection (OpenCV Haar cascade, bundled with opencv-python,
    no extra model download needed) — gives a face center position for
    dynamic reframe tracking instead of a fixed center-crop
  - computes a motion score (frame-difference magnitude vs the previous
    sample) — this is the actual "is this an action/clip-able moment"
    signal, independent of the transcript. A keyword-based highlight tag
    only catches moments someone described in words; this catches visual
    activity spikes (a fight, a fast camera pan, a big on-screen event)
    even when nobody said anything notable.

Output: {"samples": [{"time": 12.0, "face_center": [0.52, 0.41] or null,
                       "motion_score": 0.23}, ...]}
motion_score is normalized roughly 0-1 (not a hard bound — relative
frame-diff magnitude, meant for comparing samples within one video, not
across videos).
"""
import argparse
import json
import sys

try:
    import cv2
    import numpy as np
except ImportError:
    cv2 = None


def classify_frame(gray):
    """Heuristic loading-screen / low-content detector: real gameplay has
    rich visual detail (edges, texture, varied color) across the whole
    frame; a loading screen is overwhelmingly a flat/near-flat background
    with maybe a logo, spinner, or progress bar — low edge density AND
    low pixel variance. Requiring BOTH conditions (not just one) avoids
    misflagging a genuinely simple-but-real gameplay frame (e.g. staring
    at a plain sky) as a loading screen.
    Returns True if this frame looks like a loading/menu screen."""
    variance = float(np.var(gray))
    edges = cv2.Canny(gray, 50, 150)
    edge_density = float(np.count_nonzero(edges)) / edges.size
    return variance < 400 and edge_density < 0.02


def analyze(video_path, interval_sec=2.0):
    if cv2 is None:
        return None

    # Real bug fixed: face detection setup used to crash the ENTIRE
    # analysis if CascadeClassifier wasn't available in this particular
    # opencv build — but motion detection (VideoCapture/absdiff/resize)
    # doesn't depend on it at all. Face detection now degrades to
    # "unavailable" instead of taking down clip selection with it.
    cascade = None
    try:
        cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        cascade = cv2.CascadeClassifier(cascade_path)
        if cascade.empty():
            cascade = None
    except AttributeError:
        cascade = None  # this cv2 build doesn't have CascadeClassifier/objdetect at all

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return None

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
    duration = frame_count / fps if fps else 0
    frame_interval = max(1, int(round(fps * interval_sec)))

    samples = []
    prev_gray_small = None
    frame_idx = 0

    while True:
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ok, frame = cap.read()
        if not ok:
            break

        t = frame_idx / fps
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        h, w = gray.shape[:2]

        # face detection on the full-res grayscale frame (skipped entirely
        # if the cascade isn't available in this cv2 build — motion score
        # below still works either way)
        face_center = None
        face_size = None
        all_faces = []
        if cascade is not None:
            faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(40, 40))
            if len(faces) > 0:
                # largest detected face (most likely the main subject, not a
                # background extra) — bbox is (x, y, width, height)
                fx, fy, fw, fh = max(faces, key=lambda b: b[2] * b[3])
                face_center = [round((fx + fw / 2) / w, 4), round((fy + fh / 2) / h, 4)]
                face_size = [round(fw / w, 4), round(fh / h, 4)]
                # up to 2 largest faces, for split-screen dual-speaker
                # tracking — face_center above stays as-is (existing
                # single-speaker callers unaffected), all_faces is new
                by_size = sorted(faces, key=lambda b: b[2] * b[3], reverse=True)[:2]
                all_faces = [[round((bx + bw / 2) / w, 4), round((by_ + bh / 2) / h, 4)]
                             for bx, by_, bw, bh in by_size]

        # motion score: downsample for speed, compare to previous sample
        small = cv2.resize(gray, (64, 36))
        motion_score = 0.0
        if prev_gray_small is not None:
            diff = cv2.absdiff(small, prev_gray_small)
            motion_score = round(float(np.mean(diff)) / 255.0, 4)
        prev_gray_small = small

        is_loading_screen = classify_frame(gray)

        samples.append({"time": round(t, 2), "face_center": face_center,
                         "face_size": face_size if face_center else None,
                         "all_faces": all_faces, "motion_score": motion_score,
                         "is_loading_screen": is_loading_screen})
        frame_idx += frame_interval
        if duration and t > duration:
            break

    cap.release()
    return {"samples": samples, "duration": duration, "interval_sec": interval_sec}


def motion_beats(analysis, z_threshold=2.0, min_gap_sec=8, window_sec=4):
    """Turns motion-score spikes into beat-like dicts tagged 'action' — the
    actual answer to 'identify clip-able moments' independent of the
    transcript: a fight, a jump-scare, a fast camera pan all show up here
    even if nobody said anything notable. Merges with beat_planner's
    transcript-based beats in clip-select, same downstream treatment.

    Uses mean + z_threshold*stdev rather than a percentile cut — a
    percentile-based threshold breaks down when spikes are a small
    minority of samples with a lot of near-identical baseline values (the
    threshold index lands inside the tied baseline block instead of above
    it). Z-score against the video's own mean/stdev is robust to that and
    is relative to THIS video's own motion distribution, not an absolute
    number — a slow talking-head video and a fast-paced game have very
    different baselines.
    """
    samples = analysis.get("samples", [])
    scores = [s["motion_score"] for s in samples]
    if len(scores) < 2:
        return []

    mean = sum(scores) / len(scores)
    variance = sum((x - mean) ** 2 for x in scores) / len(scores)
    stdev = variance ** 0.5
    if stdev <= 0:
        return []  # perfectly uniform motion (or a static video) — nothing stands out

    threshold = mean + z_threshold * stdev

    beats = []
    last_beat_end = -min_gap_sec
    for s in samples:
        if s["motion_score"] <= threshold:
            continue
        if s["time"] - last_beat_end < min_gap_sec:
            continue  # too close to the last flagged spike, avoid spam
        start = max(0, s["time"] - window_sec / 2)
        end = s["time"] + window_sec / 2
        beats.append({
            "start": round(start, 2), "end": round(end, 2),
            "text": "(visual action detected)", "tags": ["action"],
        })
        last_beat_end = end
    return beats


def main():
    p = argparse.ArgumentParser()
    p.add_argument("video_path")
    p.add_argument("out_json_path")
    p.add_argument("--interval", type=float, default=2.0)
    args = p.parse_args()

    if cv2 is None:
        json.dump({"error": "opencv not installed — run: pip install opencv-python-headless"},
                   open(args.out_json_path, "w"))
        print(json.dumps({"available": False}))
        sys.exit(1)

    result = analyze(args.video_path, args.interval)
    if result is None:
        json.dump({"error": "could not open video"}, open(args.out_json_path, "w"))
        print(json.dumps({"available": False}))
        sys.exit(1)

    json.dump(result, open(args.out_json_path, "w"))
    faces_found = sum(1 for s in result["samples"] if s["face_center"])
    print(json.dumps({
        "available": True,
        "samples": len(result["samples"]),
        "samples_with_face": faces_found,
    }))


if __name__ == "__main__":
    main()
