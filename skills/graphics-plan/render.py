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


# Real root cause found and fixed: drawtext with no explicit fontfile=
# relies on fontconfig to resolve a font by NAME — and confirmed on the
# real production machine, its ffmpeg build has zero fontconfig support
# (`ffmpeg -version` shows no --enable-libfontconfig, common for Homebrew
# builds). Without fontconfig, drawtext fails hard rather than falling
# back to anything. This searches a short list of font paths that
# reliably exist on the actual platforms this pipeline runs on, and uses
# the first one found — sidesteps fontconfig entirely instead of
# depending on it.
_FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial.ttf",   # macOS
    "/System/Library/Fonts/Helvetica.ttc",            # macOS fallback
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",  # Linux (Debian/Ubuntu)
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",         # Linux (RHEL/Fedora)
]


def find_font_file():
    for path in _FONT_CANDIDATES:
        if os.path.exists(path):
            return path
    return None  # none found — caller falls back to no-fontfile (old, fontconfig-dependent) behavior


def run_ffmpeg(cmd):
    """Real bug fixed: every ffmpeg call in this file used check=True with
    capture_output=True, meaning a failure raised CalledProcessError with
    the actual ffmpeg stderr message completely invisible — the Python
    traceback shown to the user (and even in our own logs) never included
    WHY ffmpeg actually failed, only that it did. This surfaces the real
    error text before re-raising, so a failure is actually diagnosable
    instead of a black box."""
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"ffmpeg FAILED (exit {result.returncode}). Real stderr:\n{result.stderr}", file=sys.stderr)
        raise subprocess.CalledProcessError(result.returncode, cmd, output=result.stdout, stderr=result.stderr)
    return result


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


def render_beat_image(text, width, height, style, font_file):
    """Renders one beat's caption as a transparent RGBA PNG the same size
    as the video frame — text + semi-transparent box, positioned per
    style — for ffmpeg's overlay filter instead of drawtext. Real,
    permanent fix: confirmed on the production machine that its ffmpeg
    build has NO drawtext filter at all ("No such filter: 'drawtext'"),
    not a font-loading issue — no fontfile parameter could ever have
    fixed that, since the filter itself doesn't exist in the binary.
    overlay, unlike drawtext, has no optional external library
    dependency, so this sidesteps the whole problem permanently
    regardless of how the user's ffmpeg was built."""
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    font_size = 42
    try:
        font = ImageFont.truetype(font_file, font_size) if font_file else ImageFont.load_default(size=font_size)
    except Exception:
        font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), text, font=font)
    text_w, text_h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (width - text_w) // 2
    y = int(height * 0.1) if "top-half" in style else int(height * 0.75)

    pad = 16
    draw.rectangle([x - pad, y - pad, x + text_w + pad, y + text_h + pad],
                   fill=(0, 0, 0, int(255 * 0.55)))
    draw.text((x, y), text, font=font, fill=(255, 255, 255, 255))
    return img


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
    return ",".join(filters)


def render_with_caption_overlays(input_path, beats, width, height, style, reframe, out_path):
    """Full replacement for the drawtext-based card rendering: base
    reframe filter (unchanged), then one PNG overlay per beat, composited
    via ffmpeg's overlay filter with enable='between(...)' — same visual
    timing behavior as the old drawtext approach, zero dependency on
    drawtext/libfreetype/fontconfig being present in the ffmpeg build."""
    import tempfile
    font_file = find_font_file()
    base_filter = build_filter(width, height, [], style, reframe)

    if not beats:
        cmd = ["ffmpeg", "-nostdin", "-y", "-i", input_path, "-vf", base_filter,
               "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac", out_path]
        run_ffmpeg(cmd)
        return 0

    with tempfile.TemporaryDirectory() as tmpdir:
        image_paths = []
        for i, beat in enumerate(beats):
            text = beat["text"]
            if len(text) > 60:
                text = text[:57] + "..."
            img = render_beat_image(text, width, height, style, font_file)
            img_path = os.path.join(tmpdir, f"beat_{i:03d}.png")
            img.save(img_path)
            image_paths.append(img_path)

        cmd = ["ffmpeg", "-nostdin", "-y", "-i", input_path]
        for p in image_paths:
            cmd += ["-i", p]

        filter_parts = [f"[0:v]{base_filter}[base]"]
        prev_label = "base"
        for i, beat in enumerate(beats):
            out_label = f"v{i}"
            filter_parts.append(
                f"[{prev_label}][{i+1}:v]overlay=0:0:enable='between(t\\,{beat['start']:.2f}\\,{beat['end']:.2f})'[{out_label}]"
            )
            prev_label = out_label

        filter_complex = ";".join(filter_parts)
        cmd += ["-filter_complex", filter_complex, "-map", f"[{prev_label}]", "-map", "0:a?",
                "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac", out_path]
        run_ffmpeg(cmd)
    return len(beats)


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
        run_ffmpeg(cmd)
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


def build_split_screen_video(rough_cut, two_speaker_segments, target_w, target_h, work_dir):
    """Split mode — two speakers, each cropped to follow their own tracked
    position, stacked top/bottom to fill the target frame. Same per-
    segment-static-crop-then-concat approach as single-speaker face
    tracking, just producing two crops per segment and stacking them
    instead of one."""
    os.makedirs(work_dir, exist_ok=True)
    src_w, src_h = ffprobe_dims(rough_cut)

    half_h = target_h // 2
    # each speaker's crop covers the full source width scaled to target_w,
    # cropped to whatever source-height slice keeps that aspect for half_h
    crop_w = src_w
    crop_h = min(src_h, round(src_w * half_h / target_w))

    part_files = []
    for i, seg in enumerate(two_speaker_segments):
        track_files = []
        for track_key, suffix in [("track_a", "top"), ("track_b", "bottom")]:
            cy_px = seg[track_key][1] * src_h
            y = max(0, min(src_h - crop_h, round(cy_px - crop_h / 2)))
            track_file = os.path.join(work_dir, f"split_{i:04d}_{suffix}.mp4")
            cmd = [
                "ffmpeg", "-nostdin", "-y", "-i", rough_cut,
                "-ss", str(seg["start"]), "-to", str(seg["end"]),
                "-vf", f"crop={crop_w}:{crop_h}:0:{y},scale={target_w}:{half_h}",
                "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac",
                track_file, "-loglevel", "error",
            ]
            run_ffmpeg(cmd)
            track_files.append(track_file)

        stacked_file = os.path.join(work_dir, f"stacked_{i:04d}.mp4")
        subprocess.run(
            ["ffmpeg", "-nostdin", "-y", "-i", track_files[0], "-i", track_files[1],
             "-filter_complex", "[0:v][1:v]vstack=inputs=2[v]",
             "-map", "[v]", "-map", "0:a?",
             "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac",
             stacked_file, "-loglevel", "error"],
            check=True, capture_output=True, text=True,
        )
        part_files.append(stacked_file)

    concat_list = os.path.join(work_dir, "concat.txt")
    with open(concat_list, "w") as f:
        for pf in part_files:
            f.write(f"file '{os.path.abspath(pf)}'\n")

    concat_out = os.path.join(work_dir, "split_screen.mp4")
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
    two_speaker_segments = []
    if face_track_path and os.path.exists(face_track_path):
        try:
            data = json.load(open(face_track_path))
            segs = data.get("segments", [])
            if segs and "track_a" in segs[0]:
                two_speaker_segments = segs
            elif reframe == "crop":
                face_segments = segs
        except Exception:
            pass

    show_captions = ("card" in style or "hook" in style) and beats

    if reframe == "split" and two_speaker_segments:
        work_dir = os.path.join(os.path.dirname(out_path), "_split_work")
        stacked = build_split_screen_video(rough_cut, two_speaker_segments, width, height, work_dir)
        if show_captions:
            render_with_caption_overlays(stacked, beats, width, height, style, "_already_cropped", out_path)
        else:
            run_ffmpeg(["ffmpeg", "-nostdin", "-y", "-i", stacked, "-c", "copy", out_path])
        import shutil
        shutil.rmtree(work_dir, ignore_errors=True)
        print(json.dumps({"beats_rendered": len(beats) if show_captions else 0,
                           "split_screen": True, "segments": len(two_speaker_segments)}))
        return

    if face_segments:
        # face-tracking path: crop+scale happens per-segment above, so
        # caption overlays (if any) apply once to the already-cropped
        # concatenated result
        work_dir = os.path.join(os.path.dirname(out_path), "_facetrack_work")
        cropped = build_face_tracked_video(rough_cut, face_segments, width, height, work_dir)
        if show_captions:
            render_with_caption_overlays(cropped, beats, width, height, style, "_already_cropped", out_path)
        else:
            run_ffmpeg(["ffmpeg", "-nostdin", "-y", "-i", cropped, "-c", "copy", out_path])
        import shutil
        shutil.rmtree(work_dir, ignore_errors=True)
        print(json.dumps({"beats_rendered": len(beats) if show_captions else 0,
                           "face_tracked": True, "face_segments": len(face_segments)}))
        return

    if show_captions:
        render_with_caption_overlays(rough_cut, beats, width, height, style, reframe, out_path)
    else:
        vf = build_filter(width, height, beats, style, reframe)
        cmd = [
            "ffmpeg", "-nostdin", "-y", "-i", rough_cut,
            "-vf", vf,
            "-c:v", "libx264", "-preset", "veryfast",
            "-c:a", "aac",
            out_path,
        ]
        run_ffmpeg(cmd)
    print(json.dumps({"beats_rendered": len(beats) if show_captions else 0,
                       "face_tracked": False}))


if __name__ == "__main__":
    main()
