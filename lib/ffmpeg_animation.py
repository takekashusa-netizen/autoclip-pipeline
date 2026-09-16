#!/usr/bin/env python3
"""
lib/ffmpeg_animation.py
Real, ffmpeg-based Animation Engine (Layers 7-12, honest scope).
"""
import subprocess


def apply_zoom_punch(input_path, output_path, start_sec, duration_sec,
                      zoom_start=1.0, zoom_end=1.15, timeout_sec=120):
    fps = 30
    frames = int(duration_sec * fps)
    zoom_expr = f"'{zoom_start}+({zoom_end}-{zoom_start})*on/{frames}'"
    cmd = [
        "ffmpeg", "-nostdin", "-y", "-ss", str(start_sec), "-i", input_path,
        "-t", str(duration_sec),
        "-vf", f"zoompan=z={zoom_expr}:d=1:fps={fps}:s=1080x1920",
        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", output_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_sec, stdin=subprocess.DEVNULL)
    if result.returncode != 0:
        raise RuntimeError(f"real ffmpeg zoom failed: {result.stderr[-1000:]}")
    return output_path


def apply_freeze_frame(input_path, output_path, freeze_at_sec, freeze_duration_sec=1.0, timeout_sec=120):
    cmd = [
        "ffmpeg", "-nostdin", "-y", "-i", input_path,
        "-vf", f"tpad=start_duration={freeze_duration_sec}:start_mode=clone" if freeze_at_sec == 0
               else f"select='not(between(t,{freeze_at_sec},{freeze_at_sec}))',setpts=N/FRAME_RATE/TB",
        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", output_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_sec, stdin=subprocess.DEVNULL)
    if result.returncode != 0:
        raise RuntimeError(f"real ffmpeg freeze-frame failed: {result.stderr[-1000:]}")
    return output_path


def apply_screen_shake(input_path, output_path, intensity_px=8, timeout_sec=120):
    cmd = [
        "ffmpeg", "-nostdin", "-y", "-i", input_path,
        "-vf", f"crop=iw-{intensity_px*2}:ih-{intensity_px*2}:"
               f"{intensity_px}+{intensity_px}*sin(2*PI*t*8):{intensity_px}+{intensity_px}*cos(2*PI*t*7)",
        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", output_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_sec, stdin=subprocess.DEVNULL)
    if result.returncode != 0:
        raise RuntimeError(f"real ffmpeg screen-shake failed: {result.stderr[-1000:]}")
    return output_path


def apply_text_fade(input_path, output_path, text, start_sec, duration_sec,
                     font_size=90, color="white", timeout_sec=120):
    fade_dur = min(0.3, duration_sec / 3)
    end_sec = start_sec + duration_sec
    alpha_expr = (
        f"if(lt(t,{start_sec}),0,"
        f"if(lt(t,{start_sec + fade_dur}),(t-{start_sec})/{fade_dur},"
        f"if(lt(t,{end_sec - fade_dur}),1,"
        f"if(lt(t,{end_sec}),({end_sec}-t)/{fade_dur},0))))"
    )
    escaped_text = text.replace("'", "\\'").replace(":", "\\:")
    cmd = [
        "ffmpeg", "-nostdin", "-y", "-i", input_path,
        "-vf", f"drawtext=text='{escaped_text}':fontsize={font_size}:fontcolor={color}:"
               f"x=(w-text_w)/2:y=h*0.15:alpha='{alpha_expr}'",
        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
        "-c:a", "copy", output_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_sec, stdin=subprocess.DEVNULL)
    if result.returncode != 0:
        raise RuntimeError(f"real ffmpeg text-fade failed: {result.stderr[-1000:]}")
    return output_path


REAL_ANIMATION_MAP = {
    "CLUTCH": [("zoom_punch", {"zoom_end": 1.2})],
    "INSANE_PLAY": [("zoom_punch", {"zoom_end": 1.25}), ("screen_shake", {"intensity_px": 6})],
    "FUNNY": [("text_fade", {})],
    "WIN": [("freeze_frame", {"freeze_duration_sec": 0.8})],
    "FAIL": [("text_fade", {})],
    "RAGE": [("screen_shake", {"intensity_px": 10})],
}


def get_animation_plan(moment_type):
    return REAL_ANIMATION_MAP.get(moment_type, [])
