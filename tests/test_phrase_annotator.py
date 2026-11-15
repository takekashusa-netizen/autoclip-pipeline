import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "lib"), os.path.join(ROOT, "skills", "clip-select"), os.path.join(ROOT, "skills", "graphics-plan")]
import phrase_annotator as P

CASES = {
    "yo chat clip that right now": "clip_call", "somebody clip it": "clip_call", "did y'all see that": "clip_call",
    "run that back": "clip_call", "that's going on the tiktok": "clip_call",
    "sit down you're cooked": "trash_talk", "skill issue": "trash_talk", "get off my screen": "trash_talk", "you're a bot": "trash_talk",
    "hahaha I'm crying": "funny", "I can't breathe": "funny", "bro what": "funny",
    "how am I dead": "rage", "are you serious right now": "rage",
    "let's goooo": "hype", "1v3 squad wipe": "hype", "oh my god": "hype",
    "hot take": "hot_take",
}
NEGATIVE = ["I'm gonna grab some water", "the bot lane was empty", "we need to rotate to the north", "okay reload real quick"]

def test_hits():
    for text, cat in CASES.items():
        assert cat in P.tags_for(text), (text, P.tags_for(text))

def test_no_false_positives():
    for text in NEGATIVE:
        assert P.tags_for(text) == [], (text, P.tags_for(text))

def test_clip_call_reaches_back_and_wins_the_window():
    import best_windows as BW
    segs = [{"start": t, "end": t + 4, "text": "rotating north okay"} for t in range(0, 600, 5)]
    segs[70] = {"start": 350, "end": 354, "text": "yo chat clip that"}   # the play is the 25s before this line
    scores, bin_sec = BW.build_interest_timeline(600, segs, None, None)
    wins = BW.find_best_windows(scores, bin_sec, 60, 1, min_score_per_min=0)
    w = max(wins, key=lambda x: x["score"])
    assert w["start"] <= 330 and w["end"] >= 350, w   # covers the play before "clip that", not just the line

if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"): f(); print("ok -", n)
    print("ALL PASS")
