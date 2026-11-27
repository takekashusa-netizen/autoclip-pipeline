#!/usr/bin/env python3
"""
lib/gaming_trends.py [--refresh]

What's hot in gaming right now, cached in gaming_trends.json (refreshed at most
once a day). Sources, best first:
  1. Twitch Helix top games (live viewership) when TWITCH_CLIENT_ID and
     TWITCH_CLIENT_SECRET are set (free app at dev.twitch.tv).
  2. Steam's public most-played chart (ISteamChartsService/GetMostPlayedGames,
     no key) plus store names.
  3. A researched seed list (Nov 2026) so it never comes back empty.

Used to (a) boost clip candidates from trending games and (b) add the
trending game's tag when it's genuinely the game in the clip.
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "gaming_trends.json")
MAX_AGE = 24 * 3600
# Seed (Nov 2026 research): Twitch State of Gaming 2026 (League of Legends top competitive title;
# GTA VI launch traffic; horror up, e.g. Dead by Daylight/Phasmophobia; Rocket League, Rainbow Six
# Siege via top creators), most-streamed by channels: Fortnite; plus this channel's own games.
SEED = ["Fortnite", "League of Legends", "Grand Theft Auto VI", "Call of Duty: Warzone", "Apex Legends",
        "Valorant", "Counter-Strike 2", "Minecraft", "Rocket League", "Tom Clancy's Rainbow Six Siege",
        "Dead by Daylight", "Phasmophobia", "NBA 2K27", "EA Sports FC 27", "Call of Duty: Modern Warfare 4",
        "Marvel Rivals", "Roblox", "Overwatch 2", "Dota 2", "Escape from Tarkov"]


def _get(url, headers=None, data=None, timeout=15):
    if os.environ.get("TAKEKASH_OFFLINE"):          # tests: never depend on live charts
        raise OSError("offline mode")
    req = urllib.request.Request(url, data=data, headers=headers or {"User-Agent": "takekash-pipeline/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def from_twitch(limit=30):
    cid, sec = os.environ.get("TWITCH_CLIENT_ID"), os.environ.get("TWITCH_CLIENT_SECRET")
    if not (cid and sec):
        return None
    tok = _get("https://id.twitch.tv/oauth2/token", data=urllib.parse.urlencode(
        {"client_id": cid, "client_secret": sec, "grant_type": "client_credentials"}).encode())["access_token"]
    d = _get(f"https://api.twitch.tv/helix/games/top?first={limit}",
             headers={"Client-Id": cid, "Authorization": f"Bearer {tok}"})
    skip = {"Just Chatting", "IRL", "Music", "Art", "Special Events", "Talk Shows & Podcasts", "Sports", "ASMR", "Slots", "Virtual Casino"}
    return [g["name"] for g in d.get("data", []) if g.get("name") not in skip]


def from_steam(limit=25):
    d = _get("https://api.steampowered.com/ISteamChartsService/GetMostPlayedGames/v1/")
    names = []
    for row in (d.get("response", {}).get("ranks") or [])[:limit]:
        try:
            info = _get(f"https://store.steampowered.com/api/appdetails?appids={row['appid']}&filters=basic")
            nm = info[str(row["appid"])]["data"]["name"]
            names.append(nm)
        except Exception:
            continue
    return names or None


def refresh():
    games, source = None, None
    for fn, name in ((from_twitch, "twitch"), (from_steam, "steam")):
        try:
            games = fn()
        except Exception as e:
            print(f"gaming_trends: {name} failed: {e}", file=sys.stderr)
            games = None
        if games:
            source = name
            break
    if not games:
        games, source = list(SEED), "seed-2026-11"
    data = {"updated": int(time.time()), "source": source, "games": games[:30]}
    with open(CACHE, "w") as fh:
        json.dump(data, fh, indent=2)
    return data


def load(max_age=MAX_AGE):
    try:
        d = json.load(open(CACHE))
        if time.time() - d.get("updated", 0) < max_age:
            return d
    except Exception:
        pass
    try:
        return refresh()
    except Exception:
        return {"updated": 0, "source": "seed-2026-11", "games": list(SEED)}


def _norm(s):
    return "".join(c for c in (s or "").lower() if c.isalnum())


def trend_rank(game, trends=None):
    """1-based rank of a game in the trending list (fuzzy: 'Warzone' matches 'Call of Duty: Warzone'), else None."""
    if not game:
        return None
    g = _norm(game)
    for i, name in enumerate((trends or load())["games"]):
        n = _norm(name)
        if g and (g == n or g in n or n in g):
            return i + 1
    return None


if __name__ == "__main__":
    d = refresh() if "--refresh" in sys.argv else load()
    print(json.dumps(d, indent=2))
