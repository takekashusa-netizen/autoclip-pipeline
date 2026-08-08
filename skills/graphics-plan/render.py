#!/usr/bin/env python3
"""
skills/graphics-plan/render.py

Stand-in for the real HyperFrames engine (which does reframe/graphics/b-roll/
motion/captions as an HTML video engine). This does the two things graphics-
plan is actually responsible for with plain ffmpeg, so the pipeline produces
a real output instead of a stub:

  1. Reframe the rough-cut to the format's target aspect/resolution
     (center-crop then scale).
  2. Burn a simple text card for each planned beat, positioned per the
     format's graphics style (top-half vs hook-card vs none for glass/zoom
     long-form, which gets reframe only).

Swap this file's body for real HyperFrames calls (per skills-lock.json) when
that engine is vendored in — the CLI interface (job/plan/format-config in,
graphics_cut.mp4 out) should stay the same so run.sh doesn't need to change.
"""
import json
import subprocess
import sys


def escape_drawtext(text):
    """Proper ffmpeg drawtext escaping, unquoted-value style. ffmpeg's filter
    parser has a well-known apostrophe bug when text is wrapped in single
    quotes (\\' inside 'quotes' does NOT work as an escaped quote — you'd
    need 'text'\\''more' gymnastics). Simplest robust fix: don't wrap the
    value in quotes at all, and backslash-escape every filtergraph-special
    character instead. Order matters: backslash first, then the rest."""
    text = text.replace("\\", "\\\\")
    for ch in [":", "'", "[", "]", ",", ";", "%"]:
        text = text.replace(ch, "\\" + ch)
    return text


def build_filter(width, height, beats, style, reframe="crop"):
    if reframe == "letterbox":
        # scale-to-fit + pad, no cropping — gaming HUD/killfeed/minimap at
        # screen edges survives instead of getting cut off by a center-crop
        filters = [
            f"scale=w={width}:h={height}:force_original_aspect_ratio=decrease",
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black",
        ]
    else:
        # center-crop to target aspect, then scale — default for podcast/IRL
        # where the subject is usually centered and cropping the sides is fine
        filters = [
            f"crop='min(iw,ih*{width}/{height})':'min(ih,iw*{height}/{width})'",
            f"scale={width}:{height}",
        ]

    if "card" in style or "hook" in style:
        for beat in beats:
            text = escape_drawtext(beat["text"])
            if len(text) > 60:
                text = text[:57] + "..."
            y = "h*0.1" if "top-half" in style else "h*0.75"
            filters.append(
                "drawtext=text=%s:fontcolor=white:fontsize=42:"
                "box=1:boxcolor=black@0.55:boxborderw=16:"
                "x=(w-text_w)/2:y=%s:enable='between(t\\,%.2f\\,%.2f)'"
                % (text, y, beat["start"], beat["end"])
            )

    return ",".join(filters)


def main():
    rough_cut, plan_path, width, height, style, out_path = sys.argv[1:7]
    reframe = sys.argv[7] if len(sys.argv) > 7 else "crop"
    width, height = int(width), int(height)

    plan = json.load(open(plan_path))
    beats = plan.get("beats", [])

    vf = build_filter(width, height, beats, style, reframe)
    cmd = [
        "ffmpeg", "-y", "-i", rough_cut,
        "-vf", vf,
        "-c:v", "libx264", "-preset", "veryfast",
        "-c:a", "aac",
        out_path,
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    print(json.dumps({"beats_rendered": len(beats) if ("card" in style or "hook" in style) else 0}))


if __name__ == "__main__":
    main()
