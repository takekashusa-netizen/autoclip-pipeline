#!/usr/bin/env python3
"""
skills/graphics-plan/render.py

Stand-in for the real HyperFrames engine (which does reframe/graphics/b-roll/
motion/captions as an HTML video engine). This does the two things graphics-
plan is actually responsible for with plain ffmpeg, so the pipeline produces
a real output instead of a stub:

  1. Reframe the rough-cut to the format's target aspect/resolution
     (center-crop then scale, OR face-tracking crop when face position
     data is available — see build_face_tracked_video below).
  2. Burn a simple text card for each planned beat, positioned per the
     format's graphics style (top-half vs hook-card vs none for glass/zoom
     long-form, which gets reframe only).

Swap this file's body for real HyperFrames calls (per skills-lock.json) when
that engine is vendored in — the CLI interface (job/plan/format-config in,
graphics_cut.mp4 out) should stay the same so run.sh doesn't need to change.
"""
import json
import os
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


def ffprobe_dims(video_path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", video_path],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    w, h = out.split(",")
    return int(w), int(h)


def build_face_tracked_video(rough_cut, face_segments, target_w, target_h, work_dir):
    """Renders one static-crop segment per face-tracking window (average
    face position within that window), then concats them — the frame
    follows the speaker across position changes between segments, without
    needing a continuously-animated per-frame ffmpeg expression (which
    risks the same kind of crash a long generated expression caused
    elsewhere in this pipeline). Returns the path to the concatenated,
    cropped-and-scaled (but not yet drawtext'd) video."""
    os.makedirs(work_dir, exist_ok=True)
    src_w, src_h = ffprobe_dims(rough_cut)

    # crop box size in real pixels — same aspect-fit math as the static
    # path, just evaluated with real numbers now that we know source dims
    crop_w = min(src_w, round(src_h * target_w / target_h))
    crop_h = min(src_h, round(src_w * target_h / target_w))

    part_files = []
    for i, seg in enumerate(face_segments):
        cx_px = seg["center_x"] * src_w
        cy_px = seg["center_y"] * src_h
        x = max(0, min(src_w - crop_w, round(cx_px - crop_w / 2)))
        y = max(0, min(src_h - crop_h, round(cy_px - crop_h / 2)))

        part_file = os.path.join(work_dir, f"facepart_{i:04d}.mp4")
        cmd = [
            "ffmpeg", "-nostdin", "-y", "-i", rough_cut,
            "-ss", str(seg["start"]), "-to", str(seg["end"]),
            "-vf", f"crop={crop_w}:{crop_h}:{x}:{y},scale={target_w}:{target_h}",
            "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac",
            part_file, "-loglevel", "error",
        ]
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        part_files.append(part_file)

    concat_list = os.path.join(work_dir, "concat.txt")
    with open(concat_list, "w") as f:
        for pf in part_files:
            f.write(f"file '{os.path.abspath(pf)}'\n")

    concat_out = os.path.join(work_dir, "face_tracked.mp4")
    subprocess.run(
        ["ffmpeg", "-nostdin", "-y", "-f", "concat", "-safe", "0",
         "-i", concat_list, "-c", "copy", concat_out, "-loglevel", "error"],
        check=True, capture_output=True, text=True,
    )
    return concat_out


def main():
    rough_cut, plan_path, width, height, style, out_path = sys.argv[1:7]
    reframe = sys.argv[7] if len(sys.argv) > 7 else "crop"
    face_track_path = sys.argv[8] if len(sys.argv) > 8 else None
    width, height = int(width), int(height)

    plan = json.load(open(plan_path))
    beats = plan.get("beats", [])

    face_segments = []
    if face_track_path and os.path.exists(face_track_path) and reframe == "crop":
        try:
            data = json.load(open(face_track_path))
            face_segments = data.get("segments", [])
        except Exception:
            face_segments = []

    if face_segments:
        # face-tracking path: crop+scale happens per-segment above, so the
        # filter here is JUST the drawtext overlay, applied once to the
        # already-cropped concatenated result — keeps the well-tested
        # drawtext logic completely unchanged and reused as-is
        work_dir = os.path.join(os.path.dirname(out_path), "_facetrack_work")
        cropped = build_face_tracked_video(rough_cut, face_segments, width, height, work_dir)
        vf = build_filter(width, height, beats, style, reframe="_already_cropped")
        # strip the crop/scale filters build_filter would normally add —
        # reuse only its drawtext-building logic by re-deriving just that part
        drawtext_filters = [f for f in vf.split(",") if f.startswith("drawtext")]
        cmd = ["ffmpeg", "-nostdin", "-y", "-i", cropped]
        if drawtext_filters:
            cmd += ["-vf", ",".join(drawtext_filters)]
        cmd += ["-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac", out_path]
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        import shutil
        shutil.rmtree(work_dir, ignore_errors=True)
        print(json.dumps({"beats_rendered": len(beats) if ("card" in style or "hook" in style) else 0,
                           "face_tracked": True, "face_segments": len(face_segments)}))
        return

    vf = build_filter(width, height, beats, style, reframe)
    cmd = [
        "ffmpeg", "-nostdin", "-y", "-i", rough_cut,
        "-vf", vf,
        "-c:v", "libx264", "-preset", "veryfast",
        "-c:a", "aac",
        out_path,
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    print(json.dumps({"beats_rendered": len(beats) if ("card" in style or "hook" in style) else 0,
                       "face_tracked": False}))


if __name__ == "__main__":
    main()
