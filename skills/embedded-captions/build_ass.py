#!/usr/bin/env python3
"""
skills/embedded-captions/build_ass.py

Turns rough-cut's kept_segments into a burned-in .ass subtitle file.
Applies presets/caption-corrections.json (upstream brand/spelling fixes)
before writing lines. Position/style come from the format config, matching
the diagram's "short-form only, burn-in on-beat" behavior.
"""
import json
import re
import sys


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


def alignment_for_position(position):
    # ASS \an alignment codes: 2=bottom-center, 5=middle-center, 8=top-center
    pos = (position or "").lower()
    if "low" in pos or "bottom" in pos:
        return 2
    if "top" in pos:
        return 8
    return 5  # centered


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

    for seg in script.get("kept_segments", []):
        text = apply_corrections(seg["text"].strip(), corrections)
        if not text:
            continue
        text = escape_ass_text(text)
        lines.append(
            f"Dialogue: 0,{ass_time(seg['start'])},{ass_time(seg['end'])},Default,{text}\n"
        )

    with open(out_path, "w") as f:
        f.writelines(lines)

    print(json.dumps({"caption_lines": len(lines) - 1}))


if __name__ == "__main__":
    main()
