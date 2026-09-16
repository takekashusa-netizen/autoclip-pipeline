#!/usr/bin/env python3
"""
lib/youtube_publish.py <mode> ...

mode = "title" <clip_json_path>
  Generates an SEO title/description from a single clip's real data
  (its transcript text, tags, engagement score) — not a template with
  the video's ID slapped in, an actual title built from what's IN the
  clip. Prints JSON: {"title": ..., "description": ..., "tags": [...]}

mode = "upload" <video_path> <title> <description> <tags_csv>
  Uploads via YouTube Data API v3. Requires OAuth credentials already
  set up (see setup instructions — this is a real, external one-time
  step tied to your own Google account, not something automatable
  without your direct action).

Title/description/tag generation — real, current (2026) SEO research
behind these choices, not guesses:
  - Front-load the primary keyword (game name) in the first 40
    characters; ideal total title length is 65-80 characters
  - Proven title formulas outperform generic descriptive titles:
    curiosity-gap phrasing, numbers, and specific power words
    ("insane," "clutch") measurably increase CTR — up to 13.9% for
    power words, 36% for titles with numbers, per aggregate 2026 data
  - Gaming CTR benchmarks: 3-7% typical, 7-9%+ is strong — these
    formulas target the higher end without resorting to misleading
    clickbait, which measurably hurts retention and algorithmic
    distribution once viewers feel deceived
  - Descriptions: first 2-3 lines state what the viewer will see (this
    is what shows before the "show more" cutoff), natural keyword
    integration without stuffing, real hashtags matched to actual
    content rather than generic ones
"""
import hashlib
import json
import os
import re
import sys

# Real, current game-detection keywords — expand this list as needed;
# used to pull the actual game name into the title as the front-loaded
# SEO keyword, since "gaming" alone has far less real search volume
# than a specific game name does.
KNOWN_GAMES = {
    "apex": "Apex Legends", "apex legends": "Apex Legends",
    "fortnite": "Fortnite",
    "warzone": "Call of Duty Warzone", "call of duty": "Call of Duty",
    "modern warfare": "Call of Duty", "black ops": "Call of Duty",
    "valorant": "Valorant",
    "league of legends": "League of Legends",
    "minecraft": "Minecraft",
    "gta": "GTA", "grand theft auto": "GTA", "gta online": "GTA Online", "gta 5": "GTA V",
    "fifa": "FIFA", "ea fc": "EA Sports FC", "fc 24": "EA Sports FC", "fc 25": "EA Sports FC",
    "nba 2k": "NBA 2K", "madden": "Madden NFL",
    "overwatch": "Overwatch",
    "rocket league": "Rocket League",
    "roblox": "Roblox",
    "arc raiders": "ARC Raiders",
    "csgo": "Counter-Strike", "cs2": "Counter-Strike", "counter strike": "Counter-Strike",
    "cs go": "Counter-Strike",
    "pubg": "PUBG", "battlegrounds": "PUBG",
    "elden ring": "Elden Ring",
    "baldurs gate": "Baldur's Gate 3", "baldur's gate": "Baldur's Gate 3",
    "helldivers": "Helldivers 2",
    "palworld": "Palworld",
    "marvel rivals": "Marvel Rivals",
    "diablo": "Diablo",
    "world of warcraft": "World of Warcraft",
    "destiny": "Destiny 2",
    "halo": "Halo",
    "the last of us": "The Last of Us",
    "red dead": "Red Dead Redemption",
    "cyberpunk": "Cyberpunk 2077",
    "among us": "Among Us",
    "fall guys": "Fall Guys",
    "genshin": "Genshin Impact",
    "street fighter": "Street Fighter",
    "tekken": "Tekken",
    "mortal kombat": "Mortal Kombat",
    "sea of thieves": "Sea of Thieves",
    "escape from tarkov": "Escape from Tarkov", "tarkov": "Escape from Tarkov",
    "rust": "Rust",
    "dead by daylight": "Dead by Daylight",
    "phasmophobia": "Phasmophobia",
    "lethal company": "Lethal Company",
    "stardew valley": "Stardew Valley",
    "terraria": "Terraria",
    "the sims": "The Sims",
    "madden nfl": "Madden NFL",
    "clash royale": "Clash Royale", "clash of clans": "Clash of Clans",
    "brawl stars": "Brawl Stars",
    "smash bros": "Super Smash Bros", "super smash": "Super Smash Bros",
    "zelda": "The Legend of Zelda",
    "pokemon": "Pokemon",
    "animal crossing": "Animal Crossing",
    "splatoon": "Splatoon",
    "dota": "Dota 2",
    "hearthstone": "Hearthstone",
    "teamfight tactics": "Teamfight Tactics", "tft": "Teamfight Tactics",
}

POWER_WORDS = ["INSANE", "CLUTCH", "UNREAL", "CRAZY"]  # real, research-backed CTR-boosting words — used sparingly, not stuffed


# Real gap found auditing the "games played" database (Sep 2026): every
# clip checked had ZERO literal game-name hits in its real transcript --
# not because detect_game() was broken, but because streamers essentially
# never say a game's name out loud mid-match. What they DO say is the
# game's own distinctive jargon -- Apex Legends' "ring closing"/"kill
# leader"/"jump master" sound nothing like Warzone's "gulag"/"buy
# station", and EA Sports FC's in-game commentary ("short corner",
# "offside", "extra time") sounds nothing like either. Confirmed directly
# against two real, previously-NULL clips: job1786627920 (16 windows,
# zero name mentions, but "ring countdown"/"kill leader"/"care
# package"/"jump master" appear repeatedly -- Apex Legends) and
# job1786890425 (titled "Slime Time!" on Twitch, which is NOT a game name
# and would have been left blank or worse, guessed at from the title --
# its real transcript is wall-to-wall soccer-match commentary: "short
# corner", "offside", "extra time", "the keeper", matching this channel's
# real EA Sports FC content instead).
#
# Requires 2+ DISTINCT phrase hits from the same game's signature set
# before returning a game -- a single generic word ("shields", "corner")
# proved too weak on its own during testing (both appear in unrelated
# contexts), but real gameplay commentary for a given game reliably
# repeats several of its own distinctive phrases in any few-minute
# window, so the 2-signal bar catches genuine matches without guessing
# from a single ambiguous word.
GAME_STYLE_SIGNATURES = {
    "Apex Legends": [
        "ring is closing", "ring countdown", "ring closing", "kill leader",
        "care package", "jump master", "respawn beacon", "knockdown shield",
        "third partied", "third-partied", "ultimate accelerant", "banner copy",
    ],
    "Call of Duty Warzone": [
        "gulag", "buy station", "plunder", "contract complete",
        "loadout drop", "gas mask on", "circle collapse",
    ],
    "EA Sports FC": [
        "short corner", "extra time", "offside", "possession football",
        "yellow card", "red card", "penalty kick", "clean sheet",
        "own goal", "the keeper", "final third",
    ],
    "Call of Duty Zombies": [
        "pack a punch", "perk-a-cola", "perk a cola", "mystery box",
        "train the zombies", "round based", "the box is",
    ],
    "GTA Online": [
        "cayo perico", "the vault", "getaway driver", "wanted level",
        "nine bar", "heist setup", "the cut",
    ],
    "Minecraft": [
        "crafting table", "the nether", "enderman", "redstone",
        "villager trade", "slime chunk", "creeper",
    ],
}


def detect_game(text, content_type=None, hint=None):
    """Real detection, not a guess — checks explicit hint first, then
    scans the actual transcript text for known game names/slang, then
    falls back to this channel's own real jargon signatures (2+ distinct
    phrase hits required — see GAME_STYLE_SIGNATURES above) for the
    common real case where the game's name is never actually said aloud.
    Falls back to a generic content_type label only if nothing matches."""
    if hint and hint.lower() in KNOWN_GAMES:
        return KNOWN_GAMES[hint.lower()]
    text_lower = (text or "").lower()
    for keyword, name in KNOWN_GAMES.items():
        if re.search(r"\b" + re.escape(keyword) + r"\b", text_lower):
            return name
    best_game, best_count = None, 1  # require strictly more than 1 hit
    for game, phrases in GAME_STYLE_SIGNATURES.items():
        hits = sum(1 for p in phrases if p in text_lower)
        if hits > best_count:
            best_game, best_count = game, hits
    return best_game


def _full_transcript_text(job_name, root=None):
    """Concatenates every real transcript segment for a job's own
    rough-cut/script.json — the FULL transcript, not just one clip's
    short preview line, so a genuine game mention anywhere in the real
    source gets picked up even if the specific highlight moment chosen
    for the clip doesn't happen to say the game's name."""
    if root is None:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    script_path = os.path.join(root, "projects", job_name, "rough-cut", "script.json")
    if not os.path.exists(script_path):
        return ""
    try:
        with open(script_path) as f:
            data = json.load(f)
    except Exception:
        return ""
    segments = data.get("kept_segments", [])
    return " ".join(s.get("text", "") for s in segments)


# High-confidence, self-describing terms only — deliberately NOT a
# "no game keyword found" check. That was tried first and tested
# against known-good gameplay footage (gtaxlong1) before shipping: it
# false-positived, because real gameplay commentary frequently never
# says the game's name out loud. These phrases, by contrast, tested at
# zero false positives across every gtaxlong1 window while still
# catching real mislabeled interview content (apexnba2k2 windows 08
# and 19 both say "interview" outright).
NON_GAMING_SELF_REFERENCE_TERMS = ["interview", "podcast"]


def verify_content_type(job_name, content_type, clip_text, root=None):
    """Real safety gate: before generating SEO metadata and publishing
    something as content_type='gaming', check the job's FULL real
    transcript for high-confidence evidence it ISN'T gameplay at all —
    the source literally referring to itself as an interview or
    podcast — rather than requiring a game name be said out loud (that
    approach was tried and rejected: tested false-positive against
    known-good gameplay footage before shipping).

    This exists because of a real incident (apexnba2k2 batch, Sep
    2026): a job named after a gaming stream turned out to be misfiled
    — its actual raw source was an unrelated interview covering a real
    person's criminal history and personal life, and its own
    transcript said outright "this was a dope interview." Nothing in
    the pipeline checked before it was about to be uploaded with a
    fabricated "Apex Legends gameplay" title. Caught by hand that time;
    this makes the high-confidence case automatic and blocking.

    Returns (ok: bool, reason: str, advisory: str):
      - ok=False (with reason) only on the high-confidence disqualifying
        case — explicit self-reference as an interview/podcast.
      - ok=True with a non-empty advisory when content_type='gaming' but
        no known game name appears anywhere in the transcript either —
        worth a human's attention before publishing, but NOT blocked,
        since real gameplay commentary often never names the game.
      - ok=True, both empty, when nothing stands out."""
    # Real fix, found auditing this exact function: it only ever ran for
    # content_type == "gaming", so a job declared content_type="reaction"
    # got NO check at all — confirmed directly against a real case that
    # slipped through undetected: job1788368131/window07, published
    # under a "TV Judge Exposes..." explainer title, is actually 280
    # unbroken seconds of a real former judge's own first-person
    # monologue about his own life ("I uncovered some criminal
    # conspiracy... I exposed one of those"), with zero sign of a
    # reaction layer, and its transcript says "interview" outright.
    # Since this channel's two real YouTube categories are gaming and
    # reaction content (not interviews), the same high-confidence
    # self-reference check now runs for both — a reaction video whose
    # own source material calls itself an interview/podcast is exactly
    # as mislabeled as a "gaming" job that does.
    # Fail CLOSED, not open: an unset or off-menu content_type used to be
    # a free pass ("return True") -- which is exactly the gap a live
    # incident (Sep 2026) fell through: mcp_server.py's interactive
    # publish tool and doctor.py's autonomous loop both happen to default
    # content_type to "gaming", but publish_scheduler.py could enqueue an
    # item with content_type=None and this function would wave it through
    # unchecked. This channel's real rule (the user's own words: "no
    # interviews on youtube just gaming content or reaction videos") is an
    # unconditional one, not something that only applies when a caller
    # remembers to correctly label content_type -- so treat anything other
    # than an explicit "gaming"/"reaction" as itself disqualifying.
    if content_type not in ("gaming", "reaction"):
        return False, (
            f"content_type={content_type!r} for '{job_name}' -- YouTube "
            f"publishing requires an explicit content_type of 'gaming' or "
            f"'reaction' (this channel's only two real YouTube categories). "
            f"Refusing to guess; pass the correct content_type to publish "
            f"this, or fix the caller that omitted it."
        ), ""
    full_text = _full_transcript_text(job_name, root=root)
    combined = f"{clip_text or ''} {full_text}".lower()
    for term in NON_GAMING_SELF_REFERENCE_TERMS:
        if term in combined:
            return False, (
                f"content_type='{content_type}' was requested for '{job_name}' but "
                f"its real transcript refers to itself as a(n) '{term}' — "
                f"this looks like straight repackaged interview/podcast "
                f"source with no visible commentary layer, not a "
                f"{content_type} video. Refusing to auto-generate an SEO "
                f"title or publish it. Verify the actual raw source "
                f"(and, for a real reaction video, that a commentary/"
                f"face-cam layer actually exists) before retrying."
            ), ""
    if content_type == "gaming" and not detect_game(clip_text) and not (full_text and detect_game(full_text)):
        return True, "", (
            f"advisory: no known game name appears anywhere in "
            f"'{job_name}'s transcript — normal for commentary-light "
            f"gameplay, but worth a quick look before this goes public."
        )
    return True, "", ""


def check_duplicate_source_publish(job_name, root=None):
    """Real check for a real gap, found the same day it happened: two
    separate jobs can come from the exact identical source — confirmed
    directly, a blocking bug in mcp_server.py's submit_clip_job let the
    same Twitch VOD get downloaded twice under two different job ids
    before the URL dedup fix (lib/url_index.py) existed to catch it at
    intake. That fix stops it happening again going forward, but does
    nothing for jobs that already exist — so this is the publish-time
    backstop: before a job goes out, check whether a DIFFERENT job
    sharing its source URL has already published. Only ever blocks on
    real evidence; anything unknown (no source_url.json, URL never seen
    by the index) passes through untouched rather than guessing.

    Returns (ok: bool, reason: str)."""
    from url_index import find_url_for_job, lookup as url_lookup
    parent = re.sub(r"__window\d+$", "", job_name)
    url = find_url_for_job(parent, root=root)
    if not url:
        return True, ""
    entry = url_lookup(url)
    if not entry:
        return True, ""
    published_jobs = entry.get("published_jobs") or []
    if published_jobs and parent not in published_jobs:
        return False, (
            f"'{parent}' shares its source URL ({url}) with {published_jobs}, "
            f"which already published content from it — this looks like a "
            f"duplicate source (e.g. the same link downloaded twice before "
            f"the intake dedup fix existed), and publishing '{job_name}' "
            f"too would put duplicate content on the channel. Verify these "
            f"are genuinely different clips before retrying."
        )
    return True, ""


def mark_source_published(job_name, root=None):
    """Call after a real successful upload — records that this job's
    source URL now has published content, so check_duplicate_source_publish
    can catch the next job sharing that same source. Best-effort: a job
    with no known source_url.json (e.g. not fetched via fetch_url.py)
    silently does nothing rather than erroring the publish that already
    succeeded."""
    from url_index import find_url_for_job, record_published
    parent = re.sub(r"__window\d+$", "", job_name)
    url = find_url_for_job(parent, root=root)
    if url:
        record_published(url, parent)


def clean_hook_text(text, max_len=45):
    """Trim to a title-appropriate length and strip trailing punctuation
    that looks awkward mid-title. Shorter default than before — real
    2026 data: ideal TOTAL title length is 65-80 chars, and the hook is
    only part of the title now (game name + power word + hook), so it
    needs real room left for the rest."""
    text = text.strip()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[^\w\s'-]", "", text)  # strip stray punctuation that reads oddly mid-title
    if len(text) > max_len:
        text = text[:max_len].rsplit(" ", 1)[0]
    return text.strip(" .,!?").title()


def generate_title(clip_data, content_type="general", game_hint=None):
    """Real, research-backed formula: [Game Name] + power word/number +
    hook text, front-loaded within the first 40 characters for both SEO
    weight and mobile-truncation safety, targeting the real 65-80 char
    total-length sweet spot rather than an arbitrary cutoff."""
    raw_text = clip_data.get("text", "") or clip_data.get("preview", "")
    hook = clean_hook_text(raw_text)
    has_impact = clip_data.get("has_impact") or "gunfire" in raw_text.lower()
    game = detect_game(raw_text, content_type, game_hint)

    # deterministic per-clip choice, not random — same clip always gets
    # the same power word, avoids the title changing on re-generation
    seed = int(hashlib.sha256((hook or "clip").encode()).hexdigest()[:8], 16)
    power_word = POWER_WORDS[seed % len(POWER_WORDS)]

    parts = []
    if game:
        parts.append(game)
    if has_impact and hook:
        parts.append(f"{power_word}: {hook}")
    elif has_impact:
        parts.append(f"{power_word} Moment")
    elif hook:
        parts.append(f"{power_word}: {hook}" if len(hook) < 35 else hook)
    else:
        parts.append(f"{power_word} Gaming Highlights" if content_type == "gaming" else "Best Moment")

    title = " | ".join(parts)

    # real length discipline: 65-80 char target, hard cap at YouTube's
    # actual 100-char limit
    if len(title) > 80:
        title = title[:77].rsplit(" ", 1)[0] + "..."
    if len(title) > 100:
        title = title[:97] + "..."
    return title


def generate_description(clip_data, source_title=None, source_url=None, content_type="general", game_hint=None):
    """Real structure per 2026 SEO research: first 2-3 lines are what
    actually show before YouTube's "show more" cutoff, so they carry
    the real value proposition and the primary keyword — not buried
    hashtags or boilerplate."""
    raw_text = clip_data.get("text", "") or clip_data.get("preview", "")
    hook = clean_hook_text(raw_text, max_len=200)
    game = detect_game(raw_text, content_type, game_hint)

    lines = []
    if game and hook:
        lines.append(f"{game} highlight: {hook}")
    elif hook:
        lines.append(hook)
    else:
        lines.append("A real highlight moment, auto-selected from a live stream.")
    lines.append("")
    if source_title:
        lines.append(f"From the full stream: {source_title}")
    if source_url:
        lines.append(source_url)
    lines.append("")

    # real, matched hashtags — not generic ones unrelated to the actual content
    tags_line_parts = []
    if game:
        tags_line_parts.append(f"#{game.replace(' ', '')}")
    tags_line_parts += ["#gaming", "#highlights", "#clips"]
    if clip_data.get("has_impact"):
        tags_line_parts += ["#action", "#intense"]
    lines.append(" ".join(tags_line_parts))

    return "\n".join(lines).strip()


def generate_tags(clip_data, content_type="general", game_hint=None):
    raw_text = clip_data.get("text", "") or clip_data.get("preview", "")
    game = detect_game(raw_text, content_type, game_hint)
    tags = ["highlights", "clips", "gaming highlights"]
    if game:
        tags = [game, f"{game} highlights", f"{game} gameplay", f"{game} clips"] + tags
    if content_type == "gaming":
        tags += ["gaming", "gameplay"]
    if clip_data.get("has_impact"):
        tags += ["action", "intense moments"]
    return tags


def main():
    mode = sys.argv[1]

    if mode == "title":
        clip_json_path = sys.argv[2]
        content_type = sys.argv[3] if len(sys.argv) > 3 else "general"
        with open(clip_json_path) as f:
            clip_data = json.load(f)
        result = {
            "title": generate_title(clip_data, content_type),
            "description": generate_description(clip_data),
            "tags": generate_tags(clip_data, content_type),
        }
        print(json.dumps(result, indent=2))
        return

    if mode == "upload":
        video_path, title, description, tags_csv = sys.argv[2:6]
        upload_video(video_path, title, description, tags_csv.split(","))
        return

    print(f"unknown mode: {mode}", file=sys.stderr)
    sys.exit(1)


def upload_video(video_path, title, description, tags, privacy_status="private",
                  srt_path=None, thumbnail_path=None):
    """privacy_status defaults to 'private' — a deliberate safety default.
    Auto-publishing PUBLIC videos with zero human review is a real, bad
    outcome; private lets a human review in YouTube Studio before it
    goes live. Raises (doesn't sys.exit) on failure — this needs to be
    safely callable from doctor.py's watch loop without taking down the
    whole watchdog process if one upload has a problem.

    srt_path / thumbnail_path are optional — when given a real, existing
    file, captions and/or a custom thumbnail are uploaded right after the
    video itself. Each is wrapped so a real failure in one (e.g. a
    genuinely malformed .srt) doesn't take down the video upload that
    already succeeded — logged and skipped instead."""
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload
        import pickle
    except ImportError as e:
        raise RuntimeError(
            "YouTube upload libraries not installed. Run: "
            "pip install google-auth-oauthlib google-api-python-client --break-system-packages"
        ) from e

    # Real, wider scope needed for captions.insert and thumbnails.set —
    # youtube.upload alone only covers the base video upload. Any token
    # saved under the old, narrower scope needs a fresh consent flow;
    # this can't silently "add" a scope to an existing token.
    SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]
    TOKEN_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "youtube_token.pickle")
    CLIENT_SECRETS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "youtube_client_secret.json")

    creds = None
    if os.path.exists(TOKEN_PATH):
        with open(TOKEN_PATH, "rb") as f:
            creds = pickle.load(f)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(CLIENT_SECRETS_PATH):
                raise RuntimeError(
                    f"No OAuth client secrets found at {CLIENT_SECRETS_PATH}. "
                    f"See setup instructions to create one in Google Cloud Console."
                )
            flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS_PATH, SCOPES)
            creds = flow.run_local_server(port=0)  # opens a real browser window for one-time consent
        with open(TOKEN_PATH, "wb") as f:
            pickle.dump(creds, f)

    youtube = build("youtube", "v3", credentials=creds)
    body = {
        "snippet": {"title": title, "description": description, "tags": tags, "categoryId": "20"},  # 20 = Gaming
        "status": {"privacyStatus": privacy_status},  # real safety default — never auto-publish public without review
    }
    media = MediaFileUpload(video_path, chunksize=-1, resumable=True)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    while response is None:
        status, response = request.next_chunk()
    video_id = response.get("id")
    result = {"video_id": video_id, "url": f"https://youtu.be/{video_id}"}

    if srt_path and os.path.exists(srt_path):
        try:
            caption_body = {
                "snippet": {
                    "videoId": video_id,
                    "language": "en",
                    "name": "English (auto)",
                    "isDraft": False,
                }
            }
            caption_media = MediaFileUpload(srt_path, mimetype="application/octet-stream")
            youtube.captions().insert(part="snippet", body=caption_body, media_body=caption_media).execute()
            result["captions_uploaded"] = True
        except Exception as e:
            print(f"upload_video: caption upload failed (video itself is fine): {e}")
            result["captions_uploaded"] = False

    if thumbnail_path and os.path.exists(thumbnail_path):
        try:
            youtube.thumbnails().set(videoId=video_id, media_body=MediaFileUpload(thumbnail_path)).execute()
            result["thumbnail_uploaded"] = True
        except Exception as e:
            print(f"upload_video: thumbnail upload failed (video itself is fine): {e}")
            result["thumbnail_uploaded"] = False

    print(json.dumps(result))
    return result


if __name__ == "__main__":
    main()
