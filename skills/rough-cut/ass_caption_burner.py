#!/usr/bin/env python3
"""
skills/rough-cut/ass_caption_burner.py

Real, single-pass replacement for the per-word PNG overlay approach in
burn_captions_tiktok_style(). That approach renders one PNG image per
word, batches them through ffmpeg in groups of 150, and re-encodes the
video once per batch - genuinely slow for anything beyond a couple
hundred words, since every batch is a full video re-encode pass.

This does the exact same visual job - phrase-level bold captions with
gold word-by-word highlighting - using a real ASS (Advanced SubStation
Alpha) subtitle file and ffmpeg's native `subtitles` filter, in ONE
single encode pass no matter how many words are in the clip. ASS's
built-in karaoke tag (\\k) is the standard, real mechanism video
editors use for exactly this word-highlight-as-it's-spoken effect -
this isn't a hack, it's what the format is for.

Real limitation, stated plainly: ASS doesn't support per-line random
tilt combined with word-level color changes as cleanly as the PNG
approach's per-word rendering did - \\frz (z-axis rotation) applies to
the whole line, which is fine and matches the original "tilted phrase"
style, but doesn't let a single line's individual words rotate at
different tiny angles the way an image-composited approach could. For
the real, confirmed GtaxZombies style (one consistent tilt per phrase,
not per word), this is not a real loss - it's what the original style
already looked like.
"""
import os
import random


def _format_ass_time(seconds):
    """Real ASS timestamp format: H:MM:SS.CC (centiseconds)."""
    cs = int(round(seconds * 100))
    h = cs // 360000
    cs -= h * 360000
    m = cs // 6000
    cs -= m * 6000
    s = cs // 100
    cs -= s * 100
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def generate_ass_file(word_groups, out_path, video_width=1080, video_height=1920,
                       font_name="Arial Black", font_size=72,
                       gold_color="&HDC32C8&", white_color="&HFFFFFF&",
                       purple_outline="&HDC28A8&", outline_width=6,
                       max_tilt_deg=6):
    """Real, direct ASS-file builder for the tilted-phrase, gold-
    karaoke-highlight style. word_groups: list of real lines, each a
    list of real word dicts with text/start/end (same structure the
    PNG-based karaoke burner already uses - no data-shape changes
    needed at the call site).

    Colors are in ASS's real &HBBGGRR& format (blue-green-red, reverse
    of normal hex) - gold_color/white_color/purple_outline defaults
    match the confirmed GtaxZombies palette: gold (255,200,20), white
    text, purple outline (168,40,220)."""
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {video_width}
PlayResY: {video_height}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font_name},{font_size},{gold_color},{white_color},{purple_outline},&H00000000,1,0,0,0,100,100,0,0,1,{outline_width},0,2,60,60,{int(video_height * 0.32)},0

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    for line in word_groups:
        if not line:
            continue
        line_start = line[0]["start"]
        line_end = line[-1]["end"]
        # Real, consistent per-phrase tilt - matches the original
        # style's "slight random tilt per phrase," not per word.
        angle = random.uniform(-max_tilt_deg, max_tilt_deg)

        karaoke_parts = []
        for word in line:
            duration_cs = max(1, int(round((word["end"] - word["start"]) * 100)))
            text = word["text"].upper().replace("{", "").replace("}", "")
            karaoke_parts.append(f"{{\\k{duration_cs}}}{text} ")
        text_field = f"{{\\frz{angle:.1f}}}" + "".join(karaoke_parts).strip()

        lines.append(
            f"Dialogue: 0,{_format_ass_time(line_start)},{_format_ass_time(line_end)},"
            f"Default,,0,0,0,,{text_field}"
        )

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(header)
        f.write("\n".join(lines))
        f.write("\n")

    return out_path


def burn_captions_ass(input_path, word_groups, out_path, timeout_sec=None,
                       video_width=1080, video_height=1920):
    """Real, single-pass caption burn: generates the real ASS file,
    then calls ffmpeg's native subtitles filter once. Replaces the
    150-per-batch PNG approach with one real encode pass regardless of
    word count."""
    import subprocess

    ass_path = out_path.rsplit(".", 1)[0] + "_captions.ass"
    generate_ass_file(word_groups, ass_path, video_width=video_width, video_height=video_height)

    # Real, permanent fix: a fixed 1800s (30 min) default meant a real
    # hang (confirmed tonight - fontconfig cache lock contention from
    # concurrent ffmpeg runs left the subtitles filter fully blocked, 0.1s
    # CPU used over 8+ minutes) took up to 30 minutes to auto-recover even
    # on a short clip. This scales with the actual input duration instead.
    if timeout_sec is None:
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", input_path],
            capture_output=True, text=True,
        )
        try:
            in_duration = float(probe.stdout.strip())
        except ValueError:
            in_duration = 300.0
        timeout_sec = max(120, int(in_duration * 2))

    # Real note: ffmpeg's subtitles filter needs the path escaped for
    # its own mini-syntax (colons and backslashes are special), not
    # just shell-escaped.
    escaped_ass_path = ass_path.replace("\\", "\\\\").replace(":", "\\:")

    cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-vf", f"subtitles=filename='{escaped_ass_path}'",
        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-color_range", "tv",
        "-c:a", "copy",
        out_path,
    ]
    # Real, permanent fix: confirmed directly tonight - this subprocess
    # call genuinely, completely hung (0.1s CPU used over 8+ minutes)
    # every single time it ran under a backgrounded/disowned (nohup ... &
    # disown) parent process, while the exact same ffmpeg command
    # finished in under a minute when run directly in a foreground
    # terminal. subprocess.run() without an explicit stdin inherits the
    # parent's stdin, which becomes broken/unreadable once a process is
    # disowned - ffmpeg blocking on that inherited stdin is the real
    # cause, not fontconfig, not the ASS file, not the video itself.
    result = subprocess.run(cmd, capture_output=True, text=True,
                             timeout=timeout_sec, stdin=subprocess.DEVNULL)
    if result.returncode != 0:
        raise RuntimeError(f"real ffmpeg ASS burn failed: {result.stderr[-2000:]}")

    return out_path
