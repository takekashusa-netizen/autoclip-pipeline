#!/usr/bin/env python3
"""
lib/self_repair.py
Real Self-Repair Engine (Layer 23).
"""
import os
import shutil
import subprocess


def attempt_repair(video_path, qc_result, max_attempts=3):
    from quality_control import check_clip_quality

    current_path = video_path
    current_result = qc_result

    for attempt in range(max_attempts):
        if current_result["quality_score"] >= 70:
            break

        checks = current_result["checks"]
        repaired_something = False
        temp_path = current_path + f".repair{attempt}.mp4"

        if checks.get("audio_not_silent") is False:
            subprocess.run(
                ["ffmpeg", "-nostdin", "-y", "-i", current_path,
                 "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
                 "-c:v", "copy", temp_path],
                capture_output=True, timeout=120, stdin=subprocess.DEVNULL,
            )
            if os.path.exists(temp_path) and os.path.getsize(temp_path) > 0:
                repaired_something = True

        elif checks.get("black_frames_ok") is False:
            duration = checks.get("duration_sec", 0)
            black_sec = checks.get("black_frame_sec", 0)
            if duration > black_sec + 1:
                subprocess.run(
                    ["ffmpeg", "-nostdin", "-y", "-i", current_path,
                     "-ss", "0.5", "-t", str(max(1, duration - black_sec)),
                     "-c", "copy", temp_path],
                    capture_output=True, timeout=120, stdin=subprocess.DEVNULL,
                )
                if os.path.exists(temp_path) and os.path.getsize(temp_path) > 0:
                    repaired_something = True

        if not repaired_something:
            break

        current_path = temp_path
        current_result = check_clip_quality(current_path)

    if current_path != video_path and os.path.exists(current_path):
        if current_result["quality_score"] > qc_result["quality_score"]:
            shutil.move(current_path, video_path)
            current_path = video_path
        else:
            os.remove(current_path)
            current_path = video_path
            current_result = qc_result

    return current_path, current_result
