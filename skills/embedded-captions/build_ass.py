#!/usr/bin/env python3
"""
skills/embedded-captions/build_ass.py

Turns rough-cut's kept_segments into a burned-in .ass subtitle file.
Applies presets/caption-corrections.json (upstream brand/spelling fixes)
before writing lines. Position/style come from the format config, matching
the diagram's "short-form only, burn-in on-beat" behavior.

Word-level animated highlighting (karaoke-style, via ASS's \\k tag) when
per-word timestamps are available in the transcript — each word
highlights as it's spoken, rather than the whole line appearing/
disappearing at once. Falls back to whole-segment display when word
timing isn't present (older script.json files, or whisperx which
doesn't provide per-word timing), so this never breaks existing jobs.
"""
import json
import re
import sys

# Simple, deterministic keyword -> emoji matching — NOT generative (no
# image/video model involved), just a curated dictionary appended after
# a matching word. Intentionally small and conservative: better to miss
# an opportunity than to inject an emoji that reads as random noise.
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
    """Appends at most ONE emoji per line, matched against the first
    keyword hit — multiple emoji per short caption line reads as noisy,
    not exciting."""
    lowered = text.lower()
    for keyword, emoji in EMOJI_KEYWORDS.items():
        if re.search(rf"\b{re.escape(keyword)}\b", lowered):
            return f"{text} {emoji}"
    return text


def ass_time(seconds):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:d}:{m:02d}:{s:05.2f}"


def apply_corrections(text, corrections):
    for wrong, right in corrections.items():
        text = re.sub(rf"\b{re.escape(wrong)}\b", right, text, flags=re.IGNORECASE)
    return text


def escape_ass_text(text):
    """ASS dialogue text treats { and } as override-tag delimiters and \\N
    as a forced line break — unescaped curly braces or backslashes from a
    real transcript ('use {config} like this') would either vanish or get
    interpreted as style overrides instead of being displayed."""
    text = text.replace("\\", "\\\\")
    text = text.replace("{", "\\{").replace("}", "\\}")
    text = text.replace("\n", "\\N")
    return text


def build_karaoke_text(words, seg_start, highlight_color="&H0000FFFF&"):
    """ASS \\k tags take CENTISECONDS of duration for each syllable/word
    to be highlighted, applied cumulatively from the line's start time —
    this is the standard, well-established ASS mechanism video editors
    use for word-by-word karaoke-style captions. \\1c sets the
    highlighted-word color, \\r resets to the default style color after.
    """
    parts = []
    prev_end = seg_start
    for w in words:
        word_text = escape_ass_text(w["word"])
        dur_cs = max(1, round((w["end"] - w["start"]) * 100))
        gap_cs = max(0, round((w["start"] - prev_end) * 100))
        if gap_cs > 0:
            parts.append(f"{{\\k{gap_cs}}}")
        parts.append(f"{{\\k{dur_cs}\\1c{highlight_color}}}{word_text}{{\\r}}")
        prev_end = w["end"]
    return "".join(parts)


HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, Bold, Alignment, MarginV
Style: Default,Arial,{fontsize},&H00FFFFFF,&H00000000,1,{alignment},{marginv}

[Events]
Format: Layer, Start, End, Style, Text
"""


def main():
    script_path, corrections_path, out_path, width, height, position = sys.argv[1:7]
    width, height = int(width), int(height)

    script = json.load(open(script_path))
    corrections = {}
    try:
        corrections = json.load(open(corrections_path)).get("corrections", {})
    except FileNotFoundError:
        pass

    alignment = alignment_for_position(position)
    marginv = 200 if alignment == 2 else 80
    fontsize = max(36, width // 22)

    lines = [HEADER.format(width=width, height=height, fontsize=fontsize,
                            alignment=alignment, marginv=marginv)]

    word_level_count = 0
    for seg in script.get("kept_segments", []):
        raw_text = seg["text"].strip()
        if not raw_text:
            continue
        text = apply_corrections(raw_text, corrections)
        words = seg.get("words") or []

        if words:
            # correct corrections/emoji against the WHOLE line first (so a
            # correction spanning word boundaries still applies), but the
            # per-word karaoke highlighting still uses ORIGINAL word
            # boundaries/timing from whisper — corrections are cosmetic
            # text swaps, not re-timed speech
            text_with_emoji = inject_emoji(text)
            karaoke_text = build_karaoke_text(words, seg["start"])
            # append the emoji (if any) as a plain, non-highlighted trailing token
            emoji_suffix = text_with_emoji[len(text):]  # just the " 🔥" part, if added
            body = karaoke_text + escape_ass_text(emoji_suffix)
            word_level_count += 1
        else:
            body = escape_ass_text(inject_emoji(text))

        lines.append(
            f"Dialogue: 0,{ass_time(seg['start'])},{ass_time(seg['end'])},Default,{body}\n"
        )

    with open(out_path, "w") as f:
        f.writelines(lines)

    print(json.dumps({"caption_lines": len(lines) - 1, "word_level_lines": word_level_count}))


def alignment_for_position(position):
    # ASS \an alignment codes: 2=bottom-center, 5=middle-center, 8=top-center
    pos = (position or "").lower()
    if "low" in pos or "bottom" in pos:
        return 2
    if "top" in pos:
        return 8
    return 5  # centered


if __name__ == "__main__":
    main()
