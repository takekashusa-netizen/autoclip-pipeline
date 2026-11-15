#!/usr/bin/env python3
"""
lib/phrase_annotator.py <script.json> [out.json]

Finds the lines that make a clip worth posting, in what the streamer (and
their squad) actually SAY:

  clip_call   "clip that", "someone clip it", "chat clip", "did y'all see that",
              "run that back", "that's going on TikTok" ... the streamer telling
              you it's a clip. Said AFTER the play, so the span reaches back.
  trash_talk  "sit down", "you're cooked", "too easy", "dog water", "skill issue",
              "get off my screen", "who taught you" ...
  funny       laughter, "I'm crying", "I can't breathe", "bro what", "why would you" ...
  rage        "are you serious", "how am I dead", "this game is", "I'm done" ...
  hype        "let's go", "oh my god", "no way", "1v3", "squad wipe", "sheesh" ...
  hot_take    "real talk", "hot take", "unpopular opinion", "storytime" ...

Each hit: {"start", "end", "category", "phrase", "text", "weight", "lookback"}.
Used by clip selection (score + reach-back) and written to
rough-cut/annotations.json for captions/metadata.
"""
import json
import re
import sys

# (category, weight, seconds to reach back before the line, patterns)
RULES = [
    ("clip_call", 5.0, 25.0, [
        r"\bclip (that|it|this)\b", r"\b(some ?(one|body)|chat|y'?all|mods?) (go )?clip\b", r"\bgo clip\b",
        r"\bthat'?s (a|the) clip\b", r"\bthat'?s (going|goin'?) (on|to) (the |my )?(tiktok|youtube|channel|highlights?|reel)\b",
        r"\bput that on (the |my )?(tiktok|youtube|channel|highlights?)\b", r"\b(run|play) (that|it) back\b",
        r"\breplay that\b", r"\bdid (you|y'?all|chat|you guys) (just )?see that\b", r"\btell me (you|y'?all) saw that\b",
        r"\bno way that just happened\b", r"\bget the clip\b", r"\bsave that\b",
    ]),
    ("trash_talk", 3.0, 6.0, [
        r"\bsit (yo(ur)? (ass|self) )?down\b", r"\bsat (him|her|them|you|em) down\b", r"\b(you'?re|he'?s|they'?re|you are) (so )?(cooked|done|trash|washed|dog ?water|free)\b",
        r"\btoo easy\b", r"\b(ez|e z|easy) (clap|game|dub)\b", r"\bdog ?water\b", r"\bskill issue\b", r"\bget off my screen\b",
        r"\bwho taught you\b", r"\buninstall\b", r"\bgo home\b", r"\b(bozo|clown)s?\b", r"\b(you'?re|he'?s|she'?s|they'?re|you are|what a|such a) (a |an |such a )?(bot|npc)s?\b", r"\brent free\b",
        r"\bpack(ed)? (him|her|them|you|em) up\b", r"\bstay mad\b", r"\bcry about it\b", r"\b(get|got) (clapped|smoked|cooked|rekt|wrecked|folded)\b",
        r"\bdiff\b", r"\bratio\b", r"\bnot even close\b", r"\bin your (face|mouth)\b", r"\bwho'?s next\b",
    ]),
    ("funny", 3.0, 4.0, [
        r"\b(ha){3,}h?\b", r"\b(lmao+|lmfao|lol+)\b", r"\[(laughter|laughs?|laughing)\]", r"\bi'?m (literally )?(crying|dead|weak)\b",
        r"\bi can'?t breathe\b", r"\bbro what\b", r"\bwhy would (you|he|she|they)\b", r"\bthat'?s (so )?(crazy|wild|hilarious)\b",
        r"\bwhat (is|was) (that|bro doing)\b", r"\bbro (is|was) (trolling|tweaking|bugging)\b", r"\bi'?m (so )?done\b.*\b(ha|lol)",
    ]),
    ("rage", 3.0, 8.0, [
        r"\bare you (fucking |freaking |for )?(serious|kidding)\b", r"\bhow (am|was|did) i (dead|die|lose|miss)\b", r"\bhow did (he|she|that|they)\b",
        r"\bthis game (is|be)\b", r"\bi'?m (actually )?(done|tweaking|crashing out)\b", r"\bno (shot|way) (he|she|that)\b",
        r"\bthat'?s (bs|bullshit|cap|so cheap)\b", r"\bi (hit|shot) (him|her|them|that)\b.*\b(like|times|bro)\b", r"\bwhat the (hell|heck|f+)\b",
    ]),
    ("hype", 2.5, 8.0, [
        r"\blet'?s (go+|gooo+)\b", r"\boh my (god|gosh)\b", r"\bno way\b", r"\binsane\b", r"\bclutch\b", r"\bshee+sh\b", r"\byo+o+\b",
        r"\b1 ?v ?[2-5]\b|\bone (v|versus) (two|three|four|five)\b", r"\b(squad|team) ?wipe\b|\bwiped (them|em|the squad)\b", r"\bace\b",
        r"\bare you kidding me\b", r"\bwhat was that\b", r"\bcracked\b", r"\bdub\b|\bw+ ?(in the chat)\b",
    ]),
    ("hot_take", 1.5, 0.0, [
        r"\breal talk\b", r"\bhot take\b", r"\bunpopular opinion\b", r"\bstory ?time\b", r"\bnobody talks about\b", r"\bhear me out\b",
    ]),
]
_COMPILED = [(c, w, lb, [re.compile(p, re.I) for p in pats]) for c, w, lb, pats in RULES]
CATEGORY_WEIGHTS = {c: w for c, w, _, _ in RULES}


def annotate_text(text):
    """All (category, weight, lookback, phrase) hits in one line, strongest per category."""
    hits = {}
    for cat, w, lb, pats in _COMPILED:
        for rx in pats:
            m = rx.search(text or "")
            if m:
                hits[cat] = (cat, w, lb, m.group(0))
                break
    return list(hits.values())


def annotate(segments):
    out = []
    for seg in segments or []:
        for cat, w, lb, phrase in annotate_text(seg.get("text", "")):
            out.append({"start": round(max(0.0, seg["start"] - lb), 2), "end": round(seg["end"] + 2.0, 2),
                        "said_at": seg["start"], "category": cat, "phrase": phrase, "weight": w, "lookback": lb,
                        "text": seg.get("text", "").strip()[:200]})
    return out


def tags_for(text):
    """Tags for beat_planner.classify()."""
    return [cat for cat, *_ in annotate_text(text)]


def summary(annotations):
    by = {}
    for a in annotations:
        by.setdefault(a["category"], 0)
        by[a["category"]] += 1
    return by


def main():
    script = json.load(open(sys.argv[1]))
    ann = annotate(script.get("kept_segments", []))
    out = {"annotations": ann, "counts": summary(ann)}
    if len(sys.argv) > 2:
        json.dump(out, open(sys.argv[2], "w"), indent=2)
    print(json.dumps(out["counts"]))


if __name__ == "__main__":
    main()
