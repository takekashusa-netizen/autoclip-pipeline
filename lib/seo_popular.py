"""Popular-tag layer for TakeKash SEO: what people actually search, ranked, per topic.

Two sources, merged:
  1. LIVE  - YouTube search-suggest (the same list people see while typing), no API key.
             Queried for the video's topics + "shorts", ranked by position and repeat
             appearances, cached 24 h in data/seo_popular_cache.json. Runs wherever the
             internet is open (Mac, Railway). If blocked, silently skipped.
  2. BANK  - a ranked tag bank per topic (research Nov 2026: Shorts/TikTok/IG hashtag
             studies, displaypurposes/virlo/iqhashtags volume data). Order = popularity.

Rules baked in (checked Nov 2026):
  Shorts   3-5 hashtags; the first 3 show above the title; >60 hashtags = all ignored;
           #shorts is a convention, not a requirement (we keep it first: categorisation);
           ~40 title characters show in the feed -> hook + main keyword first.
  YouTube  tags field 500 chars total.   TikTok 3-5 hashtags (#fyp + niche + brand).
  Instagram hard cap 5 hashtags.
"""
import json, os, re, time, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(os.path.dirname(HERE), "data", "seo_popular_cache.json")
TTL = 24 * 3600

# topic -> detector regex, ranked hashtags (most popular first), ranked search tags
BANK = {
    "shorts":   (r".", ["#shorts", "#youtubeshorts", "#viral"], ["shorts", "youtube shorts", "viral shorts", "trending shorts"]),
    "anime":    (r"\b(anime|manga|otaku|cartoon|animated|toon)\b",
                 ["#anime", "#animeedit", "#animeart", "#animeshorts", "#otaku", "#manga", "#animefyp"],
                 ["anime", "anime edit", "anime shorts", "anime art", "anime character", "anime animation", "manga", "otaku", "new anime"]),
    "samurai":  (r"\b(samurai|ronin|katana|bushido|blade|sword|dojo)\b",
                 ["#samurai", "#katana", "#ronin", "#bushido", "#japan"],
                 ["samurai", "black samurai", "samurai anime", "katana", "ronin", "samurai warrior", "samurai sword", "bushido"]),
    "animation":(r"\b(animation|animated|motion comic|character|mascot|edit|amv)\b",
                 ["#animation", "#characterdesign", "#motioncomic", "#2danimation"],
                 ["animation", "character design", "motion comic", "character animation", "original character", "animated short"]),
    "gaming":   (r"\b(gaming|gamer|game|gameplay|warzone|apex|2k|fortnite|cod|call of duty|mw4|gta|valorant|fps|clutch)\b",
                 ["#gaming", "#gamingclips", "#gamingshorts", "#gamer", "#gameplay"],
                 ["gaming", "gaming clips", "gaming shorts", "gameplay", "gamer", "gaming highlights"]),
    "streamer": (r"\b(stream|streamer|streaming|twitch|live|vod|chat|kick)\b",
                 ["#twitch", "#streamer", "#twitchstreamer", "#twitchclips", "#smallstreamer"],
                 ["twitch streamer", "twitch clips", "streamer", "live streaming", "small streamer", "how to grow on twitch", "stream highlights"]),
    "ai":       (r"\b(ai|clip studio|clipping|auto ?clip|tool|software|app|seo generator|automat)\w*",
                 ["#aitools", "#ai", "#aivideo", "#techtok"],
                 ["ai tools", "ai video", "ai clip generator", "auto clip", "ai video editor", "repurpose content", "clip maker"]),
    "creator":  (r"\b(creator|content|editing|editor|editflow|overlay|seo|caption|tags|hashtags|youtube|tiktok|views|grow)\w*",
                 ["#contentcreator", "#creatortips", "#videoediting", "#youtubetips"],
                 ["content creator", "content creation", "video editing", "youtube tips", "grow on youtube", "short form content", "stream overlay"]),
    "brand":    (r".", ["#takekash", "#gtaxzombies"], ["takekash", "take kash", "takekash.com", "gtaxzombies", "kash"]),
}
# hashtags that ride on every platform's broad slot
BROAD = {"tiktok": "#fyp", "instagram": None, "shorts": "#shorts", "youtube": None}


def topics(text):
    t = (text or "").lower()
    hits = []
    for name, (rx, _, _) in BANK.items():
        if name in ("shorts", "brand"):
            continue
        n = len(re.findall(rx, t))
        if n: hits.append((n, name))
    return [n for _, n in sorted(hits, key=lambda x: -x[0])]


# ---------------- live: YouTube search-suggest
def _load_cache():
    try: return json.load(open(CACHE))
    except Exception: return {}


def _save_cache(c):
    try:
        os.makedirs(os.path.dirname(CACHE), exist_ok=True)
        json.dump(c, open(CACHE, "w"), indent=1)
    except Exception:
        pass


_OFFLINE = {"down": bool(os.environ.get("SEO_OFFLINE") or os.environ.get("TAKEKASH_OFFLINE"))}

def suggest(q, timeout=3):
    """YouTube's own autocomplete for q (ranked). [] when offline/blocked.
    One failure trips a breaker so a blocked network never slows a batch down."""
    c = _load_cache(); k = "yt:" + q.lower()
    if k in c and time.time() - c[k]["t"] < TTL:
        return c[k]["s"]
    if _OFFLINE["down"]:
        return []
    url = "https://suggestqueries.google.com/complete/search?client=firefox&ds=yt&q=" + urllib.parse.quote(q)
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=timeout) as r:
            s = [x for x in json.loads(r.read().decode("utf-8", "ignore"))[1] if isinstance(x, str)]
    except Exception:
        _OFFLINE["down"] = True
        return []
    c[k] = {"t": time.time(), "s": s}; _save_cache(c)
    return s


def live_tags(seeds, per=8):
    """Rank suggestions across seeds: earlier position + appearing for several seeds = more popular."""
    score = {}
    for seed in seeds:
        for i, s in enumerate(suggest(seed)[:per]):
            s = re.sub(r"\s+", " ", s.strip().lower())
            if 2 < len(s) <= 60:
                score[s] = score.get(s, 0) + (per - i)
    return [s for s, _ in sorted(score.items(), key=lambda kv: -kv[1])]


# ---------------- public API
def hashtags(text, platform="shorts", n=5, brand=True, pinned=None):
    """Ranked hashtags for the platform: format/broad slot + niche (by topic strength) + brand.
    pinned = topics the preset declares (the video's real subject) and they rank first."""
    tps = _merge(pinned, topics(text)) or ["creator"]
    niche = []
    for tp in tps:                         # round-robin across topics so the top tag of each lands first
        niche.append(BANK[tp][1])
    ordered = []
    for i in range(max((len(l) for l in niche), default=0)):   # bounded: never loops forever
        for lst in niche:
            if i < len(lst): ordered.append(lst[i])
    out = []
    b = BROAD.get(platform)
    if b: out.append(b)
    for h in ordered:
        if h not in out: out.append(h)
    if brand:
        out = out[: n - 1] + ["#takekash"]
    return out[:n]


def _merge(pinned, found):
    out = [t for t in (pinned or []) if t in BANK]
    return out + [t for t in found if t not in out]


def tags(text, extra=(), live=True, limit=60, pinned=None):
    """Ranked YouTube search tags: brand, live suggestions for the topics, then the bank."""
    tps = _merge(pinned, topics(text)) or ["creator"]
    pool = list(extra) + BANK["brand"][2][:3]
    if live:
        seeds = [w for tp in tps[:3] for w in BANK[tp][2][:2]] + [BANK[tps[0]][2][0] + " shorts"]
        pool += live_tags(seeds)
    for tp in tps:
        pool += BANK[tp][2]
    pool += BANK["shorts"][2]
    seen, out = set(), []
    for t in pool:
        t = t.strip().lower()
        if t and t not in seen:
            seen.add(t); out.append(t)
    return out[:limit]


def shorts_pack(subject, hook, lines, links=(), brand_line="", live=True, pinned=None):
    """Complete Shorts/TikTok/IG metadata from a subject + hook + body lines.
    Returns dict(platform -> {title, description, hashtags, tags?})."""
    import seo_finalize as SF
    text = " ".join([subject, hook] * 3 + list(lines))      # the hook/subject outweigh the body copy
    yt_hash = hashtags(text, "shorts", 5, pinned=pinned)
    title = f"{hook} | {subject}".strip(" |")
    title = re.sub(r"\s+", " ", title)
    if len(title) > 92: title = title[:92].rsplit(" ", 1)[0]
    title_s = f"{title} #shorts"
    cta = "👍 Like, 💬 comment & 🔁 share if this hits."
    body = "\n\n".join([l for l in lines if l] + [cta] + [l for l in links if l] + ([brand_line] if brand_line else []))
    yt_tags, used = SF.pack_youtube_tags(tags(text, live=live, pinned=pinned))
    tk_hash = hashtags(text, "tiktok", 5, pinned=pinned)
    ig_hash = hashtags(text, "instagram", 5, pinned=pinned)
    tk_body = "\n\n".join([l for l in lines if l] + [cta.replace("this hits", "KASH should be the face of the brand") if "KASH" in text else cta, "Link in bio → takekash.com"])
    return {
        "shorts": {"title": title_s[:100], "description": (body + "\n\n" + " ".join(yt_hash)).strip()[:5000],
                   "hashtags": yt_hash, "tags": yt_tags, "tag_chars": used},
        "tiktok": {"title": hook[:60], "description": (tk_body + "\n\n" + " ".join(tk_hash))[:4000], "hashtags": tk_hash},
        "instagram": {"description": (tk_body + "\n\n" + " ".join(ig_hash))[:2200], "hashtags": ig_hash},
        "topics": _merge(pinned, topics(text)), "live_suggestions_used": bool(live and live_tags([subject]))}
