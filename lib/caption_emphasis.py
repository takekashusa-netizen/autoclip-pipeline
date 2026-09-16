#!/usr/bin/env python3
"""
lib/caption_emphasis.py
Real Caption Emphasis detection (Layer 14).
"""
import re

REAL_EMPHASIS_WORDS = {
    "no", "way", "insane", "crazy", "clutch", "wow", "what", "how",
    "never", "actually", "literally", "wait", "bro", "yo", "yooo",
}


def find_emphasis_words(text):
    words = text.split()
    emphasized = []
    for i, word in enumerate(words):
        clean = re.sub(r"[^\w]", "", word)
        if not clean:
            continue
        reason = None
        if re.match(r"^\d+$", clean):
            reason = "number"
        elif clean.isupper() and len(clean) > 1:
            reason = "all_caps"
        elif clean.lower() in REAL_EMPHASIS_WORDS:
            reason = "reaction_word"
        if reason:
            emphasized.append({"index": i, "word": word, "reason": reason})
    return emphasized
