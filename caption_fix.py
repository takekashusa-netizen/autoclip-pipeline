#!/usr/bin/env python3
"""Fix broken post captions before they go out.

Your recent TikTok captions shipped with JSON leaking into them, e.g.
  '#MarvinGaye", "#MotownHistory", "#JacksonFive'
and garbled tags like '#podcastclipscastClips'. TikTok can't read those as hashtags,
so the posts lose topic matching. Use clean_caption() on every caption before posting.
"""
import json, re

TAG_RE = re.compile(r"#?([A-Za-z0-9_]+)")

def garbled(tag):
    """True when a 4+ letter chunk repeats inside the tag, e.g. podcastclipscastClips, reactiontion."""
    t = tag.lower()
    return any(t.count(t[i:i + 4]) > 1 for i in range(len(t) - 3))

def normalize_tags(raw, limit=5):
    """Accept a list, a JSON array string, or messy text; return up to `limit` clean, unique hashtags."""
    if isinstance(raw, str):
        s = raw.strip()
        try:
            parsed = json.loads(s if s.startswith("[") else "[" + s + "]")
            raw = parsed if isinstance(parsed, list) else [s]
        except (json.JSONDecodeError, TypeError):
            raw = re.split(r"[\s,\"']+", s)
    out, seen = [], set()
    for item in raw:
        for m in TAG_RE.finditer(str(item)):
            tag = m.group(1)
            key = tag.lower()
            if len(tag) < 2 or key in seen or garbled(tag):
                continue
            seen.add(key); out.append("#" + tag)
            if len(out) == limit:
                return out
    return out

def clean_caption(text, tags=None, limit=5):
    """Strip leaked JSON quotes/commas and stray tags from the text, then append clean hashtags."""
    found = re.findall(r"#[^\s]+", text)
    body = re.sub(r"#[^\s]+", "", text)
    body = re.sub(r'[\\"]+\s*,\s*[\\"]+', " ", body)   # '", "' leftovers
    body = body.replace('\\"', '"').replace("\\u2014", "—")
    body = re.sub(r'(^|\s)"(\s|$)', " ", body)          # lone quote marks
    body = re.sub(r"\s{2,}", " ", body)
    body = re.sub(r'[\s,"]+$', "", body)
    body = re.sub(r"^[\s,]+", "", body)
    if body.count('"') % 2:
        i = body.rfind('"'); body = body[:i] + body[i + 1:]
    hashtags = normalize_tags(tags if tags is not None else found, limit)
    return (body + " " + " ".join(hashtags)).strip()

if __name__ == "__main__":
    tests = [
        '"Marvin Gaye\'s Final Concert" A neighbor\'s insider account. #MarvinGaye", "#MotownHistory", "#JacksonFive", "#JoeJackson", "#MusicHistory", "#TrueStory',
        '"Reacting to the Wildest Prison Story We\'ve Ever Heard" #reactiontion #podcastclipscastClips #truecrimetokCrime #Interview',
        'GOT HIM 🔥 5 hits. #ApexLegends #Gaming #ApexLegends',
    ]
    for t in tests:
        print("IN :", t); print("OUT:", clean_caption(t)); print()
    print(normalize_tags('["#Motown", "#BerryGordy", "#Motown"]'))
