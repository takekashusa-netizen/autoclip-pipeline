#!/usr/bin/env python3
"""
lib/caption_overlay.py <video_in> <script_path> <corrections_path> <video_out> <width> <height> <position>

Full-transcript caption burning via PIL-rendered PNG overlays + ffmpeg's
overlay filter — the same real, tested fix already applied to beat-card
captions in graphics-plan/render.py, extended to cover the whole-
transcript captions that embedded-captions/run.sh used to burn via
ffmpeg's `ass=` filter.

Real root cause (confirmed twice now on the production ffmpeg build):
`ffmpeg -filters` shows neither `ass`, `subtitles`, nor `drawtext` — this
build has none of the optional text-rendering filters compiled in
(missing libass AND libfreetype). overlay has no such dependency, so
this sidesteps the whole class of problem rather than patching around
one filter at a time.

One caveat, stated plainly: per-word karaoke highlighting (the
word-level animated captions feature) is NOT reproduced here — each
caption is one static image for its whole segment, not a per-word
highlight animation. Rebuilding true word-level highlighting via
image overlays would need one overlay image per WORD transition, which
is a real, larger follow-up; this fix prioritizes "captions actually
work" over "captions are animated," given the choice between the two.
"""
import json
import os
import re
import subprocess
import sys
import tempfile

EMOJI_KEYWORDS = {
    "insane": "🤯", "crazy": "🤯", "unbelievable": "🤯",
    "win": "🏆", "won": "🏆", "champion": "🏆",
    "fire": "🔥", "amazing": "🔥", "incredible": "🔥",
    "clutch": "💪", "no way": "😱", "wow": "😱",
    "love": "❤️", "funny": "😂", "hilarious": "😂", "lol": "😂",
    "money": "💰", "rich": "💰",
    "fast": "⚡", "speed": "⚡",
    "dead": "💀", "died": "💀",
    "100": "💯", "perfect": "💯",
    "warning": "⚠️", "danger": "⚠️",
    "gg": "🎮", "game": "🎮",
    "boom": "💥", "explosion": "💥",
}


def inject_emoji(text):
    lowered = text.lower()
    for keyword, emoji in EMOJI_KEYWORDS.items():
        if re.search(rf"\b{re.escape(keyword)}\b", lowered):
            return f"{text} {emoji}"
    return text


def apply_corrections(text, corrections):
    for wrong, right in corrections.items():
        text = re.sub(rf"\b{re.escape(wrong)}\b", right, text, flags=re.IGNORECASE)
    return text


def find_font_file():
    for path in [
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    ]:
        if os.path.exists(path):
            return path
    return None


def render_caption_image(text, width, height, position, font_file):
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    font_size = max(28, width // 22)
    try:
        font = ImageFont.truetype(font_file, font_size) if font_file else ImageFont.load_default(size=font_size)
    except Exception:
        font = ImageFont.load_default()

    # simple word-wrap so long lines don't run off-frame
    words = text.split()
    lines, current = [], ""
    max_line_width = width * 0.85
    for w in words:
        trial = f"{current} {w}".strip()
        bbox = draw.textbbox((0, 0), trial, font=font)
        if bbox[2] - bbox[0] > max_line_width and current:
            lines.append(current)
            current = w
        else:
            current = trial
    if current:
        lines.append(current)

    line_heights = [draw.textbbox((0, 0), ln, font=font)[3] for ln in lines]
    total_h = sum(line_heights) + (len(lines) - 1) * 6

    if "top" in (position or "").lower():
        top_y = int(height * 0.08)
    elif "low" in (position or "").lower() or "bottom" in (position or "").lower():
        top_y = int(height * 0.78) - total_h
    else:
        top_y = (height - total_h) // 2

    pad = 14
    max_line_w = max(draw.textbbox((0, 0), ln, font=font)[2] for ln in lines)
    box_x0 = (width - max_line_w) // 2 - pad
    box_x1 = (width + max_line_w) // 2 + pad
    draw.rectangle([box_x0, top_y - pad, box_x1, top_y + total_h + pad],
                   fill=(0, 0, 0, int(255 * 0.55)))

    y = top_y
    for ln, lh in zip(lines, line_heights):
        bbox = draw.textbbox((0, 0), ln, font=font)
        line_w = bbox[2] - bbox[0]
        x = (width - line_w) // 2
        draw.text((x, y), ln, font=font, fill=(255, 255, 255, 255))
        y += lh + 6

    return img


def run_ffmpeg(cmd):
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"ffmpeg FAILED (exit {result.returncode}). Real stderr:\n{result.stderr}", file=sys.stderr)
        raise subprocess.CalledProcessError(result.returncode, cmd, output=result.stdout, stderr=result.stderr)
    return result


def burn_captions(video_in, segments, width, height, position, video_out):
    if not segments:
        run_ffmpeg(["ffmpeg", "-nostdin", "-y", "-i", video_in, "-c", "copy", video_out])
        return 0

    font_file = find_font_file()
    with tempfile.TemporaryDirectory() as tmpdir:
        image_paths = []
        for i, seg in enumerate(segments):
            img = render_caption_image(seg["text"], width, height, position, font_file)
            img_path = os.path.join(tmpdir, f"cap_{i:04d}.png")
            img.save(img_path)
            image_paths.append(img_path)

        cmd = ["ffmpeg", "-nostdin", "-y", "-i", video_in]
        for p in image_paths:
            cmd += ["-i", p]

        filter_parts = []
        prev_label = "0:v"
        for i, seg in enumerate(segments):
            out_label = f"v{i}"
            filter_parts.append(
                f"[{prev_label}][{i+1}:v]overlay=0:0:enable='between(t\\,{seg['start']:.2f}\\,{seg['end']:.2f})'[{out_label}]"
            )
            prev_label = out_label

        filter_complex = ";".join(filter_parts)
        cmd += ["-filter_complex", filter_complex, "-map", f"[{prev_label}]", "-map", "0:a?",
                "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac", video_out]
        run_ffmpeg(cmd)
    return len(segments)


def main():
    video_in, script_path, corrections_path, video_out, width, height, position = sys.argv[1:8]
    width, height = int(width), int(height)

    script = json.load(open(script_path))
    corrections = {}
    try:
        corrections = json.load(open(corrections_path)).get("corrections", {})
    except FileNotFoundError:
        pass

    segments = []
    for seg in script.get("kept_segments", []):
        raw_text = seg["text"].strip()
        if not raw_text:
            continue
        text = inject_emoji(apply_corrections(raw_text, corrections))
        segments.append({"start": seg["start"], "end": seg["end"], "text": text})

    n = burn_captions(video_in, segments, width, height, position, video_out)
    print(json.dumps({"caption_lines": n}))


if __name__ == "__main__":
    main()
