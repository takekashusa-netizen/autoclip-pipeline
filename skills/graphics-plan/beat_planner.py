#!/usr/bin/env python3
"""
skills/graphics-plan/beat_planner.py

Heuristic beat-planner over rough-cut's script.json. Not an LLM pass (that's
the real upgrade path — see NOTE at bottom) but gives graphics-plan.json
actual content to render instead of an empty beats: [] stub.

Beat types detected:
  - hook       : the first kept segment (every format wants an opening beat)
  - stat       : segments containing a number/percent — good stat-card material
  - list_item  : sequential segments that look like "first/second/next/also..."
  - question   : segments ending in "?"
"""
import json
import re
import sys

ORDINAL_WORDS = {
    "first", "second", "third", "fourth", "fifth", "next", "then",
    "also", "finally", "lastly",
}
NUMBER_RE = re.compile(r"\d+(\.\d+)?\s*%?")

GAMING_HYPE_WORDS = {
    "clutch", "insane", "no way", "let's go", "lets go", "gg", "ez",
    "headshot", "one tap", "ace", "wipe", "clean", "poggers", "pog",
    "what", "oh my god", "omg", "cracked", "nasty", "sheesh",
}
KILL_RE = re.compile(r"\b(kill(ed|s)?|down(ed)?|elim(inated)?|frag)\b", re.I)


def classify(seg, index, is_first):
    text = seg["text"].strip()
    low = text.lower()
    tags = []
    if is_first:
        tags.append("hook")
    if NUMBER_RE.search(text):
        tags.append("stat")
    first_word = low.split()[0].strip(".,!?") if low.split() else ""
    if first_word in ORDINAL_WORDS:
        tags.append("list_item")
    if text.endswith("?"):
        tags.append("question")
    if any(w in low for w in GAMING_HYPE_WORDS) or KILL_RE.search(low):
        tags.append("highlight")
    return tags


def plan_beats(kept_segments):
    beats = []
    for i, seg in enumerate(kept_segments):
        tags = classify(seg, i, is_first=(i == 0))
        if tags:
            beats.append({
                "start": seg["start"],
                "end": seg["end"],
                "text": seg["text"],
                "tags": tags,
            })
    return beats


def main():
    script_path, out_path = sys.argv[1], sys.argv[2]
    script = json.load(open(script_path))
    kept = script.get("kept_segments", [])
    beats = plan_beats(kept)
    result = {
        "beats": beats,
        "beat_count": len(beats),
        "transcription_available": script.get("transcription_available", False),
    }
    if not result["transcription_available"]:
        result["note"] = (
            "rough-cut had no transcript (pass-through mode) — no beats could "
            "be identified; graphics will apply reframe/style only, no overlay cards"
        )
    json.dump(result, open(out_path, "w"), indent=2)
    print(json.dumps({"beat_count": len(beats)}))


# NOTE on the real upgrade: swap plan_beats() for a call to the Anthropic API
# with script["kept_segments"] as context, asking for beat classification +
# suggested on-screen text (shorter than the spoken line). Heuristic above is
# a reasonable placeholder — it's what a human skimming a transcript would
# flag by eye, just without judgment about which beats actually deserve a card.
if __name__ == "__main__":
    main()
