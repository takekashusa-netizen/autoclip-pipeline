import os, sys, shutil
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
import seo_finalize as S

LONG = ["#ApexLegends", "#Apex", "#ApexLegendsClips", "#ApexRanked", "#BattleRoyale", "#Gaming", "#FPS", "#Clutch", "#Squad", "#Highlights", "#Kills", "#Twitch", "#Streamer", "#GtaxZombies", "#Win"]

def item(platform, desc="Insane 1v3 clutch to win the game #apex #clutch"):
    return {"platform": platform, "title": "Insane Apex Legends 1v3 Clutch for the Win #shorts", "description": desc, "tags": list(LONG)}

def test_instagram_caps_at_5_and_actually_includes_them():
    it = S.finalize(item("instagram"))
    caption = it["title"] + "\n" + it["description"]
    assert len(S._HASH_RE.findall(caption)) == 5   # was 0 before (hashtags never reached the caption)
    assert len(caption) <= 2200

def test_tiktok_capped_to_5_grounded_first():
    it = S.finalize(item("tiktok"))
    assert len(it["tags"]) == 5 and it["tags"][0] == "#apexlegends"
    assert "#" not in it["description"]

def test_youtube_tags_are_plain_and_fit_500():
    it = S.finalize(item("youtube"))
    assert all(not t.startswith("#") for t in it["tags"])
    assert "apex legends" in it["tags"]
    assert it["tag_chars"] <= 500
    assert len(S._HASH_RE.findall(it["description"])) == 3
    assert "#" not in it["title"] and len(it["title"]) <= 100

def test_engine_enrichment_when_node_present():
    it = S.finalize(item("youtube"))
    if shutil.which("node"):
        assert it["seo_engine"] is True and len(it["tags"]) > len(LONG) // 2
    else:
        assert it["seo_engine"] is False

def test_works_without_node(monkeypatch=None):
    real = S.shutil.which
    S.shutil.which = lambda n: None
    try:
        it = S.finalize(item("instagram"))
        assert it["seo_engine"] is False and len(it["tags"]) == 5
    finally:
        S.shutil.which = real

if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"): f(); print("ok -", n)
    print("ALL PASS")
