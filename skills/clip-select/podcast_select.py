#!/usr/bin/env python3
"""
skills/clip-select/podcast_select.py <script_path> <target_minutes> <out_json_path>

Real podcast/interview-mode selection: finds the longest, most
genuinely continuous, coherent stretch of talking in the source
(distinct from best-windows' action/impact scoring), writes it in the
SAME windows.json format best_windows.py produces — so the existing,
already caption-integrated extract_best_windows.py can extract it
without needing a separate code path.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
import doctor  # noqa: E402


def main():
    script_path, target_minutes, out_path = sys.argv[1:4]
    target_minutes = float(target_minutes)

    script = json.load(open(script_path)) if os.path.exists(script_path) else {}
    kept_segments = script.get("kept_segments", []) if script.get("transcription_available") else []

    windows = doctor.find_podcast_segments(kept_segments, target_minutes=target_minutes)

    # real, same output shape as best_windows.py — {"windows": [{"start":.., "end":.., "score":..}]}
    # so extract_best_windows.py and generate_window_metadata() both work unmodified
    formatted = [{"start": w["start"], "end": w["end"], "score": w.get("density", 0)} for w in windows]
    json.dump({"windows": formatted}, open(out_path, "w"), indent=2)

    print(json.dumps({"window_count": len(formatted),
                       "durations_sec": [round(w["end"] - w["start"], 1) for w in formatted]}))


if __name__ == "__main__":
    main()
