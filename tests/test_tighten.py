"""Tighten: dead air + fillers cut from word timestamps, word-aligned hook, approval gate, exact render length."""
import json, os, subprocess, sys
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from studio import tighten  # noqa: E402
from studio.common import StudioError, probe  # noqa: E402

W = lambda a, b, w: {"start": a, "end": b, "word": w}
WORDS = [W(0.2, 0.5, "So"), W(0.55, 0.9, "today"), W(0.95, 1.3, "we"), W(1.35, 1.8, "play."),
         W(3.4, 3.6, "um"),                                                        # filler inside 1.6 s of dead air
         W(4.0, 4.3, "Why"), W(4.35, 4.6, "did"), W(4.65, 5.0, "nobody"), W(5.05, 5.3, "tell"), W(5.35, 5.8, "me?"),
         W(7.5, 7.8, "Anyway"), W(7.85, 8.3, "here.")]


@pytest.fixture
def clip(tmp_path):
    p = tmp_path / "c.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=30:duration=10",
                    "-f", "lavfi", "-i", "sine=frequency=300:duration=10", "-shortest", "-c:v", "libx264", "-preset", "veryfast",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", str(p)], check=True)
    return str(p)


def test_pacing_cuts_dead_air_and_fillers():
    spans, st = tighten.pacing(WORDS, 10.0)
    assert st["fillers"] == 1 and len(spans) == 3
    assert spans[0][0] <= 0.2 - tighten.PAD + 1e-6 and spans[1][0] <= 4.0 - tighten.PAD + 1e-6   # words never clipped
    assert all(not (s[0] < 3.5 < s[1]) for s in spans)                                       # the "um" is gone


def test_hook_is_the_question_and_word_aligned():
    best = max(tighten.sentences(WORDS), key=lambda s: tighten.score_hook(s)[0])
    assert best["text"].startswith("Why") and best["start"] == 4.0 and best["end"] == 5.8


def test_plan_approve_render(clip, tmp_path):
    cl = tighten.plan(clip, str(tmp_path), words=WORDS, hook=True)
    assert cl["hook"]["text"].startswith("Why") and cl["shots"][0]["role"] == "hook"
    assert cl["stats"]["dead_air_cut_s"] > 4 and os.path.exists(cl["storyboard"])
    with pytest.raises(StudioError):                                   # locked until approved
        tighten.render(cl["cutlist"], str(tmp_path / "o.mp4"))
    tighten.approve(cl["cutlist"])
    r = tighten.render(cl["cutlist"], str(tmp_path / "o.mp4"))
    assert abs(probe(r["out"])["duration"] - cl["stats"]["output_s"]) < 0.15
    d = json.load(open(cl["cutlist"])); d["shots"][0]["src_out"] += 1; json.dump(d, open(cl["cutlist"], "w"))
    with pytest.raises(StudioError):                                   # edited after approval -> needs a new approval
        tighten.render(cl["cutlist"], str(tmp_path / "o2.mp4"))


def test_unattended_skips_clips_without_speech(clip, tmp_path):
    assert "skipped" in tighten.make(clip, str(tmp_path / "x.mp4"), words=[])


def test_loud_gaps_are_kept_for_gaming():
    spans, _ = tighten.pacing(WORDS, 10.0, is_loud=lambda a, b: a < 3.0 < b)   # the 1.8-4.0 gap holds gunfire
    assert spans[0][0] < 1.0 and spans[0][1] > 5.5                          # play kept: first span runs through it
