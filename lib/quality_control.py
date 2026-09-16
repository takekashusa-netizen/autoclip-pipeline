#!/usr/bin/env python3
"""
lib/quality_control.py

Real, genuine Quality Control Engine. Runs real, deterministic checks
against an actual finished clip file using ffprobe/ffmpeg.
"""
import json
import os
import re
import subprocess


def _run_ffprobe(video_path, timeout_sec=30):
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "stream=width,height,codec_name,codec_type:format=duration",
         "-of", "json", video_path],
        capture_output=True, text=True, timeout=timeout_sec, stdin=subprocess.DEVNULL,
    )
    if result.returncode != 0:
        return None
    return json.loads(result.stdout)


def check_clip_quality(video_path, target_width=1080, target_height=1920, timeout_sec=60):
    checks = {}
    issues = []

    if not os.path.exists(video_path):
        return {"quality_score": 0, "checks": {}, "issues": ["file does not exist"]}

    probe = _run_ffprobe(video_path, timeout_sec)
    if probe is None:
        return {"quality_score": 0, "checks": {}, "issues": ["ffprobe failed - file may be corrupted"]}

    video_stream = next((s for s in probe.get("streams", []) if s.get("codec_type") == "video"), None)
    audio_stream = next((s for s in probe.get("streams", []) if s.get("codec_type") == "audio"), None)
    duration = float(probe.get("format", {}).get("duration", 0))

    if video_stream:
        w, h = video_stream.get("width", 0), video_stream.get("height", 0)
        checks["resolution"] = f"{w}x{h}"
        checks["resolution_match"] = (w == target_width and h == target_height)
        if not checks["resolution_match"]:
            issues.append(f"resolution {w}x{h} does not match target {target_width}x{target_height}")
        checks["video_codec"] = video_stream.get("codec_name", "")
        checks["video_codec_ok"] = checks["video_codec"] == "h264"
        if not checks["video_codec_ok"]:
            issues.append(f"video codec is {checks['video_codec']}, expected h264")
    else:
        checks["resolution_match"] = False
        checks["video_codec_ok"] = False
        issues.append("no video stream found")

    if audio_stream:
        checks["audio_codec"] = audio_stream.get("codec_name", "")
        checks["audio_codec_ok"] = checks["audio_codec"] == "aac"
        if not checks["audio_codec_ok"]:
            issues.append(f"audio codec is {checks['audio_codec']}, expected aac")
    else:
        checks["audio_codec_ok"] = False
        issues.append("no audio stream found")

    checks["duration_sec"] = duration
    checks["duration_ok"] = duration > 1.0
    if not checks["duration_ok"]:
        issues.append(f"duration {duration}s is suspiciously short or zero")

    try:
        bd_result = subprocess.run(
            ["ffmpeg", "-nostdin", "-i", video_path, "-vf", "blackdetect=d=0.5:pic_th=0.98",
             "-an", "-f", "null", "-"],
            capture_output=True, text=True, timeout=timeout_sec, stdin=subprocess.DEVNULL,
        )
        black_matches = re.findall(r"black_duration:([\d.]+)", bd_result.stderr)
        total_black = sum(float(x) for x in black_matches)
        checks["black_frame_sec"] = round(total_black, 2)
        checks["black_frames_ok"] = total_black < (duration * 0.1)
        if not checks["black_frames_ok"]:
            issues.append(f"{total_black:.1f}s of black frames detected")
    except subprocess.TimeoutExpired:
        checks["black_frames_ok"] = None
        issues.append("black-frame check timed out - skipped")

    try:
        vd_result = subprocess.run(
            ["ffmpeg", "-nostdin", "-i", video_path, "-af", "volumedetect", "-f", "null", "-"],
            capture_output=True, text=True, timeout=timeout_sec, stdin=subprocess.DEVNULL,
        )
        mean_match = re.search(r"mean_volume:\s*(-?[\d.]+)", vd_result.stderr)
        mean_db = float(mean_match.group(1)) if mean_match else -100.0
        checks["audio_mean_db"] = mean_db
        checks["audio_not_silent"] = mean_db > -50
        if not checks["audio_not_silent"]:
            issues.append(f"audio is effectively silent ({mean_db}dB)")
    except subprocess.TimeoutExpired:
        checks["audio_not_silent"] = None
        issues.append("audio level check timed out - skipped")

    boolean_checks = [v for k, v in checks.items() if isinstance(v, bool)]
    passed = sum(1 for v in boolean_checks if v)
    quality_score = int(100 * passed / max(1, len(boolean_checks)))

    return {"quality_score": quality_score, "checks": checks, "issues": issues}


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("usage: python3 quality_control.py <video_path> [target_width] [target_height]")
        sys.exit(1)
    tw = int(sys.argv[2]) if len(sys.argv) > 2 else 1080
    th = int(sys.argv[3]) if len(sys.argv) > 3 else 1920
    result = check_clip_quality(sys.argv[1], tw, th)
    print(json.dumps(result, indent=2))
