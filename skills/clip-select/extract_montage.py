#!/usr/bin/env python3
"""
skills/clip-select/extract_montage.py <script_path> <visual_path> <audio_path>
    <raw_source> <source_duration> <target_minutes> <out_dir> <job_prefix>

Real montage mode: selects the most dramatic real moments across the
whole video (not one continuous stretch), orders them chronologically to
preserve real story flow, and joins them with smooth crossfade
transitions instead of jarring hard cuts. Uses raw_source (the original,
uncut video) for extraction — the same real timeline every
transcript/visual/audio timestamp is already computed against, matching
the proven-correct pattern used by best-windows extraction.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
from clip_select import candidate_windows, select_montage_segments  # noqa: E402
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "rough-cut"))
from render_montage import render_montage  # noqa: E402


def main():
    (script_path, visual_path, audio_path, raw_source, source_duration,
     target_minutes, out_dir, job_prefix) = sys.argv[1:9]
    source_duration = float(source_duration)
    target_minutes = float(target_minutes)

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

    # Real, short candidate moments (15-60s each), reusing the same
    # proven word-boundary-snapping and loading-screen filtering already
    # used for regular clip mode.
    candidates = candidate_windows(
        kept_segments, clip_length=30.0, duration=source_duration,
        visual_analysis=visual_analysis, audio_analysis=audio_analysis,
    )

    selected, total_dur = select_montage_segments(
        candidates, target_duration_sec=target_minutes * 60,
    )

    if not selected:
        print(json.dumps({"error": "no real candidate moments met the quality bar — nothing to build a montage from"}))
        sys.exit(1)

    os.makedirs(out_dir, exist_ok=True)
    work_dir = os.path.join(out_dir, f"{job_prefix}_montage_work")
    out_path = os.path.join(out_dir, f"{job_prefix}_montage.mp4")

    render_montage(raw_source, selected, out_path, work_dir)

    print(json.dumps({
        "output": out_path,
        "segment_count": len(selected),
        "total_duration_sec": round(total_dur, 1),
        "segments": [{"start": s["start"], "end": s["end"], "score": s["score"]} for s in selected],
    }))


if __name__ == "__main__":
    main()
