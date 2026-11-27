"""Final SEO pass for every clip, run right before it publishes.

Keeps the transcript-grounded title/description/hashtags from
generate_clip_metadata, and makes them fit each platform's real rules
(checked Nov 2026), enriched by the TakeKash SEO Studio engine:

  YouTube    title <= 100; 3 hashtags at the end of the description (shown
             above the title, <= 15 total); tags field = plain search tags
             packed into the 500-character budget (commas + quotes counted)
  TikTok     3-5 hashtags (we send 5: grounded first, one broad slot)
  Instagram  hard cap of 5 hashtags per Reel; they are appended to the
             caption (they were previously missing entirely)

If Node isn't installed, the engine enrichment is skipped and the
platform limits are still enforced in pure Python.
"""
import json, os, re, shutil, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
CLI = os.path.join(HERE, "seo_engine", "cli.cjs")
HASH_CAP = {"youtube": 3, "tiktok": 5, "instagram": 5}
YT_TAG_BUDGET = 500
_HASH_RE = re.compile(r"(?<!\w)#[\wÀ-￿]+")


def _norm_hash(t):
    t = re.sub(r"[^\w]", "", str(t or "").lstrip("#"), flags=re.UNICODE)
    return f"#{t.lower()}" if t else ""


def _plain_tag(t):
    """'#ApexLegendsClips' -> 'apex legends clips' (YouTube tags are search phrases, not hashtags)."""
    t = str(t or "").lstrip("#").strip()
    t = re.sub(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Za-z])(?=\d{2,})", " ", t)
    return re.sub(r"\s+", " ", t).strip().lower()


def engine_seo(title, hashtags, platform="all", timeout=10):
    """Run the SEO Studio engine on the clip's own title + tags. None if Node is unavailable."""
    node = shutil.which("node")
    if not node or not os.path.exists(CLI):
        return None
    topic = re.sub(r"[#|:–—-]+", " ", title or "")[:180]
    extra = ", ".join(_plain_tag(h) for h in (hashtags or [])[:3])
    try:
        out = subprocess.run([node, CLI], input=json.dumps({"topic": topic, "extra": extra, "platform": platform, "seed": 7}),
                             capture_output=True, text=True, timeout=timeout, check=True)
        return json.loads(out.stdout)
    except Exception:
        return None


def pack_youtube_tags(tags, budget=YT_TAG_BUDGET):
    out, used, seen = [], 0, set()
    for t in tags:
        t = _plain_tag(t)
        if not t or t in seen or len(t) > 100:
            continue
        cost = len(t) + (2 if " " in t else 0) + (1 if out else 0)
        if used + cost > budget:
            continue
        out.append(t); used += cost; seen.add(t)
    return out, used


def pick_hashtags(grounded, engine_out, cap):
    """Transcript-grounded tags first; last slot reserved for the broad category tag (widest audience)."""
    pool = [_norm_hash(h) for h in grounded or []]
    broad = None
    if engine_out:
        T = engine_out.get("tiers") or {}
        pool += [_norm_hash(x) for x in (T.get("core") or [])[:3] if len(x.split()) <= 2]
        pool += [_norm_hash(x) for x in (T.get("similar") or [])[:3] if len(x.split()) <= 2]
        broad = _norm_hash((T.get("broad") or [None])[0])
    seen, out = set(), []
    for h in pool:
        if h and 2 < len(h) <= 30 and h not in seen and h != broad:
            seen.add(h); out.append(h)
    if broad and cap >= 3:
        out = out[: cap - 1] + [broad]
    return out[:cap]


def finalize(item):
    """Mutates and returns a publish-queue item: {platform, title, description, tags}."""
    platform = item.get("platform", "youtube")
    title = (item.get("title") or "").strip()
    desc = item.get("description") or ""
    grounded = list(item.get("tags") or []) + _HASH_RE.findall(desc) + _HASH_RE.findall(title)
    engine_out = engine_seo(title, grounded)
    # popular layer: ranked hashtags/tags people actually use for these topics (+ live YouTube suggest)
    popular_tags = []
    try:
        import seo_popular as SP
        txt = title + " " + desc + " " + " ".join(map(str, item.get("tags") or []))
        grounded += [h for h in SP.hashtags(txt, platform if platform != "youtube" else "shorts", 5, brand=False) if h != "#fyp"]
        popular_tags = SP.tags(txt, live=item.get("seo_live", True))
    except Exception:
        pass

    # hashtags never live inline in the body; we place the capped set ourselves
    body = re.sub(r"[ \t]{2,}", " ", _HASH_RE.sub("", desc)).strip()
    title = re.sub(r"\s{2,}", " ", _HASH_RE.sub("", title)).strip()  # tags are re-placed below, never left in the title
    tags = pick_hashtags(grounded, engine_out, HASH_CAP.get(platform, 5))

    if platform == "youtube":
        title = title[:100].rstrip()
        item["description"] = (body + "\n\n" + " ".join(tags)).strip()[:5000]
        yt_pool = [_plain_tag(h) for h in grounded]
        if engine_out:
            yt_pool += (engine_out.get("results", {}).get("youtube", {}).get("tags") or [])
        yt_pool += popular_tags
        item["tags"], item["tag_chars"] = pack_youtube_tags(yt_pool)
    elif platform == "instagram":
        caption_tags = " ".join(tags)
        room = 2200 - len(title) - 1 - len(caption_tags) - 2
        item["description"] = (body[: max(0, room)].rstrip() + "\n\n" + caption_tags).strip()
        item["tags"] = tags
    else:  # tiktok: publish_video's build_caption appends these to the description
        item["description"] = body
        item["tags"] = tags
    item["title"] = title
    item["seo_engine"] = bool(engine_out)
    return item
