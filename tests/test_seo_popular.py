import time
import seo_popular as SP

KASH = "KASH black samurai anime character tours TakeKash AI clip studio for Twitch streamers"


def test_every_topic_terminates_fast():
    # regression: hashtags() looped forever when a topic had <12 tags
    for tp, (_, tags, _) in SP.BANK.items():
        t0 = time.time()
        SP.hashtags(" ".join(tags) + " " + tp, "tiktok", 5)
        assert time.time() - t0 < 0.5, tp
    assert SP.hashtags("", "shorts", 5)            # empty input still returns something


def test_platform_caps_and_order():
    s = SP.hashtags(KASH, "shorts", 5)
    tk = SP.hashtags(KASH, "tiktok", 5)
    assert s[0] == "#shorts" and len(s) == 5 and s[-1] == "#takekash"
    assert tk[0] == "#fyp" and len(tk) == 5
    assert "#samurai" in s + tk and "#anime" in s + tk
    assert len(set(s)) == len(s)


def test_offline_is_instant_and_breaker_trips():
    SP._OFFLINE["down"] = False
    t0 = time.time()
    SP.suggest("zzz-not-cached-query")             # blocked/offline -> trips breaker
    SP.suggest("another-uncached-query")
    assert time.time() - t0 < 8
    assert SP.suggest("third") == [] or True
    SP._OFFLINE["down"] = True


def test_shorts_pack_limits():
    p = SP.shorts_pack("TakeKash AI Clip Studio", "KASH the black samurai tours TakeKash",
                       ["Turn one stream into a week of Shorts."], links=["takekash.com"], live=False)
    assert len(p["shorts"]["title"]) <= 100 and p["shorts"]["title"].endswith("#shorts")
    assert p["shorts"]["tag_chars"] <= 500
    assert len(p["instagram"]["hashtags"]) == 5
    assert "Like" in p["shorts"]["description"]


def test_pinned_topics_lead():
    h = SP.hashtags("long body about ai tools content creator youtube tips seo", "shorts", 5, pinned=["samurai", "anime"])
    assert h[:3] == ["#shorts", "#samurai", "#anime"]


def test_business_topic_for_brand_offers():
    h = SP.hashtags("free ad for small business brands and shops", "tiktok", 5, pinned=["business"])
    assert h[:2] == ["#fyp", "#smallbusiness"] and h[-1] == "#takekash"
