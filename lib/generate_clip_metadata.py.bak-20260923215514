#!/usr/bin/env python3
"""
lib/generate_clip_metadata.py <job_name>

Real, per-clip title/description/hashtag generator, grounded in that
specific clip's own real transcript (not the full source video) -
genuinely different from generate_social_content.py, which produces
broader LinkedIn/Twitter/email marketing content for the whole video.
"""
import json
import os
import re
import sys

PIPELINE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUTS = os.path.join(PIPELINE_ROOT, "outputs")


def generate_clip_metadata(job_name, platform="general"):
    script_path = os.path.join(PIPELINE_ROOT, "projects", job_name, "rough-cut", "script.json")
    if not os.path.exists(script_path):
        raise RuntimeError(f"no real transcript found at {script_path}")

    script = json.load(open(script_path))
    transcript_text = script.get("script_text", "")[:3000]
    return generate_clip_metadata_from_text(transcript_text, platform)


def generate_clip_metadata_from_text(transcript_text, platform="general"):
    try:
        import anthropic
    except ImportError as e:
        raise RuntimeError("anthropic package not installed. Run: pip install anthropic --break-system-packages") from e

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set in environment")

    transcript_text = transcript_text[:3000]

    platform_guidance = {
        "youtube": (
            "This is for YouTube search/discovery. Write a title (under 100 "
            "characters) that leads with the real, specific keyword phrase "
            "someone would actually type into YouTube search to find this "
            "content - not a vague teaser. Write a real, keyword-rich "
            "description of 3-5 sentences that naturally repeats the main "
            "real topic/name/subject a few times (YouTube's search index "
            "weighs description text), plus one real, specific call-to-"
            "action sentence. Include 8-12 real hashtags/tags mixing broad "
            "topic terms with specific ones actually said in the clip."
        ),
        "tiktok": (
            "This is for TikTok's search and For You algorithm. Write a "
            "short, hook-driven title (under 80 characters) using the "
            "specific real keyword phrase or name being discussed - TikTok "
            "search increasingly behaves like a real search engine, so "
            "specificity beats vague hooks. Keep the description to 1-2 "
            "punchy sentences. Include 6-8 real hashtags: 2-3 broad/trending "
            "topic tags plus specific ones grounded in what's actually said."
        ),
        "instagram": (
            "This is for Instagram Reels search and Explore. Write a title "
            "(under 90 characters) with the real, specific topic/name "
            "leading, since Instagram's search also indexes on-screen and "
            "caption text. Write a 2-3 sentence description with the real "
            "topic keywords naturally worked in. Include 6-8 real hashtags "
            "mixing broad discovery tags with specific ones from the clip."
        ),
        "general": (
            "Write a real, specific title (under 100 characters, no "
            "clickbait beyond what's genuinely in the clip), a 2-3 sentence "
            "description, and 6-8 real hashtags appropriate for "
            "TikTok/Instagram/YouTube Shorts, grounded in what's actually "
            "said above."
        ),
    }
    guidance = platform_guidance.get(platform, platform_guidance["general"])

    user_prompt = f"""Here is the real, actual transcript of one short video clip:

{transcript_text}

{guidance}

Before writing anything, identify what kind of content this genuinely
is (gaming, interview/podcast, sports/pickup game, comedy/reaction,
tutorial, commentary, etc.) from what is actually said - never assume
a genre that is not clearly present. Let that real content type drive
the hashtags: gaming clips should use the specific game name and
gaming-community tags, interview clips should use the real names and
topics discussed, sports clips should use the real sport and
team/player names, and so on - never default to gaming tags for
non-gaming content or vice versa.

Ground everything in what's genuinely said in the transcript above - no
invented claims, no generic filler. Respond with ONLY valid JSON:
{{"title": "...", "description": "...", "hashtags": ["#tag1", "#tag2", ...]}}"""

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model="claude-sonnet-5",
        max_tokens=2000,  # real, permanent fix: real thinking tokens on sensitive-topic clips were consuming the whole old 800-token budget before any real text got produced
        messages=[{"role": "user", "content": user_prompt}],
    )

    text_block = next((b for b in response.content if getattr(b, "type", None) == "text"), None)
    if text_block is None:
        raise RuntimeError("no real text block found in model response (may have been thinking-only)")
    raw_text = text_block.text.strip()
    raw_text = re.sub(r"^```(?:json)?\s*", "", raw_text)
    raw_text = re.sub(r"\s*```$", "", raw_text)

    content = json.loads(raw_text)
    required_keys = {"title", "description", "hashtags"}
    missing = required_keys - content.keys()
    if missing:
        raise RuntimeError(f"model response missing required keys: {missing}")

    return content


def main():
    """CLI entry point; accepts an optional second arg for platform-
    specific SEO guidance (youtube/tiktok/instagram/general)."""
    if len(sys.argv) < 2:
        print("usage: generate_clip_metadata.py <job_name>", file=sys.stderr)
        sys.exit(1)
    job_name = sys.argv[1]
    platform = sys.argv[2] if len(sys.argv) > 2 else "general"

    content = generate_clip_metadata(job_name, platform)

    out_path = os.path.join(OUTPUTS, f"{job_name}_metadata.json")
    with open(out_path, "w") as f:
        json.dump(content, f, indent=2)

    print(json.dumps({"output": out_path, "title": content["title"]}))


if __name__ == "__main__":
    main()


GAME_KEYWORD_TAXONOMY = {
    "apex legends": {
        "keywords": ["Apex Legends", "Ranked", "Clutch", "Movement", "FPS",
                     "Battle Royale", "Road to Masters"],
        "hashtags": ["#ApexLegends", "#Apex", "#ApexRanked", "#Gaming",
                     "#FPS", "#BattleRoyale"],
    },
    "nba 2k26": {
        "keywords": ["2K26", "Build", "Jumpshot", "3PT", "Dribble",
                     "MyCareer", "Park", "Rec", "Gameplay"],
        "hashtags": ["#NBA2K26", "#2K26", "#NBA2K", "#Build", "#Jumpshot",
                     "#ShootingGuard", "#MyCareer", "#Gaming"],
    },
    "fc 26": {
        "keywords": ["FC 26", "Ultimate Team", "Rush", "Clubs", "Gameplay",
                     "Goals", "Squad", "FUT", "Career Mode"],
        "hashtags": ["#FC26", "#EAFC26", "#UltimateTeam", "#Rush", "#Clubs",
                     "#FUT", "#Gaming", "#Football"],
    },
    "brawlhalla": {
        "keywords": ["Brawlhalla", "Legend", "Ranked", "Combos", "PvP",
                     "Gameplay", "1v1", "2v2", "Tips"],
        "hashtags": ["#Brawlhalla", "#Brawl", "#Legend", "#Ranked",
                     "#Combos", "#PvP", "#Gaming"],
    },
}


def score_clip_metadata(metadata, transcript_text, game_name=None):
    import re as _re

    title = metadata.get("title", "")
    description = metadata.get("description", "")
    hashtags = metadata.get("hashtags", [])
    text_lower = transcript_text.lower()

    title_words = [w.strip(".,!?").lower() for w in title.split() if len(w) > 3]
    real_title_words = [w for w in title_words if w in text_lower]
    search_relevance = min(100, int(70 + 30 * (len(real_title_words) / max(1, len(title_words)))))

    game_data = GAME_KEYWORD_TAXONOMY.get((game_name or "").lower(), None)
    if game_data:
        combined = (title + " " + description).lower()
        hits = sum(1 for kw in game_data["keywords"] if kw.lower() in combined)
        keyword_coverage = min(100, int(60 + 40 * (hits / max(1, len(game_data["keywords"])))))
    else:
        keyword_coverage = 80

    if game_data:
        real_tags = [h for h in hashtags if h.lower() in [t.lower() for t in game_data["hashtags"]]]
        hashtag_relevance = min(100, int(60 + 40 * (len(real_tags) / max(1, len(hashtags)))))
    else:
        hashtag_relevance = 80

    hook_signals = ["insane", "clutch", "crazy", "wild", "real", "actual", "never"]
    hook_hits = sum(1 for s in hook_signals if s in title.lower())
    hook_ctr = min(100, 75 + hook_hits * 8)

    platform_fit = 100 if len(title) <= 100 and len(hashtags) >= 4 else 75

    total = int((search_relevance + keyword_coverage + hashtag_relevance + hook_ctr + platform_fit) / 5)

    return {
        "search_relevance": search_relevance,
        "keyword_coverage": keyword_coverage,
        "hashtag_relevance": hashtag_relevance,
        "hook_ctr": hook_ctr,
        "platform_fit": platform_fit,
        "total": total,
    }


def check_duplicate_risk(title, queue_path):
    import json as _json
    try:
        with open(queue_path) as f:
            queue = _json.load(f)
    except Exception:
        return 0
    new_words = set(title.lower().split())
    if not new_words:
        return 0
    max_overlap = 0
    for item in queue:
        existing_title = item.get("title", "")
        existing_words = set(existing_title.lower().split())
        if not existing_words:
            continue
        overlap = len(new_words & existing_words) / len(new_words | existing_words)
        max_overlap = max(max_overlap, overlap)
    return int(max_overlap * 100)


def generate_clip_metadata_scored(transcript_text, platform="general", game_name=None,
                                   queue_path=None, min_score=85, max_attempts=3):
    best_metadata = None
    best_score = None
    for _attempt in range(max_attempts):
        metadata = generate_clip_metadata_from_text(transcript_text, platform)
        score = score_clip_metadata(metadata, transcript_text, game_name)
        if queue_path:
            score["duplicate_risk"] = check_duplicate_risk(metadata["title"], queue_path)
        if best_score is None or score["total"] > best_score["total"]:
            best_metadata, best_score = metadata, score
        if score["total"] >= min_score:
            break
    return best_metadata, best_score
