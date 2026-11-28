"""End-to-end tests for the Clip Studio pack on synthetic media.
Run: python3 -m pytest tests/test_studio.py -q   (needs ffmpeg + tesseract)"""
import json
import math
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from studio import (active_speaker, brand_safe, chat_moments, compilation, game_events, hook_first,  # noqa: E402
                    learning, media_kit, schedule, score_report, signals, split_layout, thumbs_titles, translate)
from studio.common import font, parse_srt, probe, write_srt  # noqa: E402

FONT = font("Bold")


def sh(*a):
    subprocess.run(a, check=True, capture_output=True)


@pytest.fixture(scope="module")
def media(tmp_path_factory):
    d = tmp_path_factory.mktemp("media")
    clip = str(d / "clip01.mp4")
    # 16:9 gameplay-ish clip: tone that gets loud at 9-10 s (the "payoff"), moving box, a webcam box top-right
    sh("ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=1920x1080:r=30:d=14",
       "-f", "lavfi", "-i", "sine=f=220:d=14",
       "-filter_complex", "[0:v]drawbox=x=1500:y=60:w=380:h=280:color=0x223344:t=fill[v];"
       "[1:a]volume='if(between(t,9,10),1.0,0.05)':eval=frame[a]",
       "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", clip)
    vert = str(d / "clip02.mp4")
    sh("ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=s=1080x1920:r=30:d=11", "-f", "lavfi", "-i",
       "sine=f=330:d=11", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest", vert)
    os.makedirs(d / "captions", exist_ok=True)
    write_srt([{"start": 0.5, "end": 2.0, "text": "yo this is crazy"},
               {"start": 2.2, "end": 4.0, "text": "what the fuck was that"},
               {"start": 9.0, "end": 10.5, "text": "NO WAY three HP"}], str(d / "captions" / "clip01.srt"))
    json.dump([{"start": 2.9, "end": 3.3, "word": "fuck"}, {"start": 9.0, "end": 9.4, "word": "NO"}],
              open(d / "clip01.words.json", "w"))
    return {"dir": str(d), "clip": clip, "vert": vert}


# ---------------------------------------------------------------- chat
def test_chat_spike_detected_and_baseline_quiet():
    msgs = []
    for t in range(0, 1800, 9):                         # ~1 msg / 9 s background
        msgs.append({"t": float(t), "user": f"u{t % 7}", "text": "gg"})
    for i in range(60):                                 # explosion at 1200 s
        msgs.append({"t": 1200 + i * 0.25, "user": f"v{i % 30}", "text": "CLIP IT no way"})
    msgs.sort(key=lambda m: m["t"])
    r = chat_moments.detect(msgs)
    assert len(r["moments"]) == 1
    m = r["moments"][0]
    assert m["start"] <= 1200 <= m["end"] and m["score"] >= 70


def test_chat_formats(tmp_path):
    p = tmp_path / "c.txt"
    p.write_text("[0:00:05] a: hi\n[0:00:06] b: CLIP\n")
    assert [m["t"] for m in chat_moments.load_chat(str(p))] == [5.0, 6.0]
    y = tmp_path / "live_chat.json"
    y.write_text(json.dumps({"replayChatItemAction": {"videoOffsetTimeMsec": "12500", "actions": [
        {"addChatItemAction": {"item": {"liveChatTextMessageRenderer": {
            "message": {"runs": [{"text": "W"}]}, "authorName": {"simpleText": "z"}}}}}]}}) + "\n")
    assert chat_moments.load_chat(str(y))[0]["t"] == 12.5


# ---------------------------------------------------------------- game events
def test_game_events_apex(tmp_path):
    v = str(tmp_path / "apex.mp4")
    sh("ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=0x223344:s=1920x1080:d=20:r=30", "-vf",
       f"drawtext=fontfile={FONT}:text='YOU ARE THE CHAMPION':fontsize=90:fontcolor=0xFFD54A:x=(w-tw)/2:y=250:enable='between(t,15,18)',"
       f"drawtext=fontfile={FONT}:text='SQUAD ELIMINATED':fontsize=70:fontcolor=white:x=(w-tw)/2:y=300:enable='between(t,6,8)',"
       f"drawtext=fontfile={FONT}:text='GtaxZombies  [R-301]  Wraith':fontsize=34:fontcolor=white:x=1230:y=60:enable='between(t,3,9)',"
       f"drawtext=fontfile={FONT}:text='GtaxZombies  [R-301]  Octane':fontsize=34:fontcolor=white:x=1230:y=110:enable='between(t,5,9)'",
       "-c:v", "libx264", "-preset", "ultrafast", v)
    r = game_events.detect(v, "apex", player="GtaxZombies")
    types = [e["type"] for e in r["events"]]
    assert types.count("kill") == 2 and "squad_wipe" in types and "win" in types
    assert r["moments"][0]["kills"] == 2


# ---------------------------------------------------------------- signals
def test_signals_merge_map_bonus(tmp_path):
    chat = {"moments": [{"start": 100, "end": 125, "peak_t": 118, "score": 70, "source": "chat", "label": "chat x5"}]}
    game = {"moments": [{"start": 105, "end": 120, "peak_t": 114, "score": 60, "source": "game", "label": "2-kill"}]}
    edl = tmp_path / "edl.json"
    edl.write_text(json.dumps({"keep": [[0, 50], [80, 300]]}))       # 30 s cut out -> shift -30
    s = signals.build(chat, game, str(edl))
    m = s["moments"][0]
    assert m["confirmed"] and m["score"] == 85 and abs(m["start"] - 70) < 0.01
    S = signals.Signals(s)
    b, why = S.bonus(60, 100)
    assert b >= 25 and why
    assert S.bonus(0, 30)[0] == 0
    ws, we = signals.window_for(m, 45, 400)
    assert ws <= m["peak_t"] <= we and we - ws == 45


def test_clip_select_imports_signals():
    sys.path.insert(0, os.path.join(ROOT, "skills", "clip-select"))
    import clip_select
    assert clip_select.Signals is not None


# ---------------------------------------------------------------- clip edits
def test_hook_first(media, tmp_path):
    out = str(tmp_path / "hook.mp4")
    r = hook_first.make(media["clip"], out, tease_text="wait for it")
    assert not r["skipped"] and 8.4 <= r["payoff"] <= 10.2 and r["payoff_source"] == "audio-peak"
    assert abs(probe(out)["duration"] - r["duration"]) < 0.4
    early = hook_first.make(media["clip"], str(tmp_path / "x.mp4"), payoff=1.0)
    assert early["skipped"]


def test_brand_safe_bleeps(media, tmp_path):
    out = str(tmp_path / "safe.mp4")
    r = brand_safe.make(media["clip"], out, check_music=False)
    assert r["out"] and len(r["profanity"]) == 1 and r["profanity"][0]["word"].startswith("f*")
    assert abs(probe(out)["duration"] - probe(media["clip"])["duration"]) < 0.2


def test_music_flag(tmp_path):
    v = str(tmp_path / "music.mp4")
    # chord + kick at 120 BPM for 20 s
    sh("ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=320x240:d=20", "-f", "lavfi", "-i",
       "aevalsrc='0.3*sin(2*PI*220*t)+0.3*sin(2*PI*277*t)+0.3*sin(2*PI*330*t)+0.9*sin(2*PI*60*t)*exp(-30*mod(t,0.5))':s=16000:d=20",
       "-shortest", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", v)
    assert brand_safe.music_spans(v)
    n = str(tmp_path / "noise.mp4")
    sh("ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=320x240:d=20", "-f", "lavfi", "-i",
       "anoisesrc=d=20:c=pink:a=0.3", "-shortest", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", n)
    assert not brand_safe.music_spans(n)


def test_split_layout(media, tmp_path):
    out = str(tmp_path / "split.mp4")
    r = split_layout.make(media["clip"], out, cam="1500,60,380,280")
    i = probe(out)
    assert (i["width"], i["height"]) == (1080, 1920) and r["cam_box"][2] > 0


def test_podcast_render_with_plan(media, tmp_path):
    out = str(tmp_path / "pod.mp4")
    r = active_speaker.make(media["clip"], out, plan={"seats": [0.25, 0.75], "changes": [(0.0, 0), (5.0, 1)]})
    assert r["cuts"] == 2 and probe(out)["height"] == 1920


def test_speaker_choice_logic():
    rows = [{"t": i / 4, "faces": [{"cx": 0.25, "motion": 5.0 if i < 20 else 0.1},
                                   {"cx": 0.75, "motion": 0.1 if i < 20 else 5.0}]} for i in range(40)]
    seats = active_speaker.assign_seats(rows)
    ch = active_speaker.choose(rows, seats, [True] * 40)
    assert len(seats) == 2 and [k for _, k in ch] == [0, 1] and 5.0 <= ch[1][0] <= 6.5


def test_translate_with_fake_and_burn(media, tmp_path):
    fake = lambda texts, lang: [f"[{lang}] {t}" for t in texts]
    r = translate.make(media["clip"], ["es"], burn=True, translator=fake, out_dir=str(tmp_path))
    cues = parse_srt(r["es"]["srt"])
    assert len(cues) == 3 and cues[0]["text"].startswith("[es]") and os.path.exists(r["es"]["video"])
    bad = lambda texts, lang: texts[:-1]
    with pytest.raises(Exception):
        translate.make(media["clip"], ["pt"], translator=bad, out_dir=str(tmp_path))


def test_thumbs_titles(media, tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    r = thumbs_titles.make(media["clip"], str(tmp_path), labels=["2-kill streak"])
    from PIL import Image
    assert Image.open(r["thumbnail"]).size == (1280, 720) and Image.open(r["cover"]).size == (1080, 1920)
    assert len(r["titles"]) == 3 and r["title_source"].startswith("fallback")


def test_score_report(tmp_path):
    rep = score_report.build("clip01", {"start": 10, "end": 55, "engagement_score": 93, "signal_bonus": 20,
                                        "signal_reasons": ["chat x5"]}, gate=90)
    assert rep["decision"] == "PASS" and rep["features"]["base_score"] == 73
    j, h = score_report.write(rep, str(tmp_path))
    assert "PASS" in open(h).read()
    assert score_report.build("c", {"engagement_score": 70}, gate=90)["decision"] == "HOLD"


def test_schedule_dry_run(media):
    q = schedule.queue(media["clip"], ["A", "B"], dry_run=True)
    assert [x["platform"] for x in q] == ["tiktok", "youtube", "instagram"] and q[2]["title"] == "A"


@pytest.mark.budget(120)
def test_compilation(media, tmp_path):
    out = str(tmp_path / "comp.mp4")
    r = compilation.build([(media["clip"], 95), (media["vert"], 91), (media["clip"], 92)], out)
    i = probe(out)
    assert (i["width"], i["height"]) == (1920, 1080) and abs(i["duration"] - r["duration"]) < 1.0
    assert r["order"][-1] == media["clip"] and r["chapters_text"].startswith("0:00")


def test_media_kit(tmp_path):
    stats = tmp_path / "s.json"
    stats.write_text(json.dumps([{"title": "Apex 20 bomb", "views": 12000, "publishedAt": "2026-11-01T00:00:00Z"},
                                 {"title": "2K green", "views": 3000, "publishedAt": "2026-06-01T00:00:00Z"}]))
    d = media_kit.gather(str(stats), str(tmp_path / "none.db"))
    assert d["youtube"]["total_views"] == 15000
    p = media_kit.render(d, str(tmp_path / "kit.html"))
    assert "15.0K" in open(p).read() and "Apex 20 bomb" in open(p).read()


def test_learning_needs_data_then_learns(tmp_path, monkeypatch):
    monkeypatch.setattr(learning, "PROFILE_DIR", str(tmp_path / "w"))
    reps, views = [], {}
    for i in range(30):
        f = {"base_score": 60 + i, "signal_bonus": (i % 3) * 10, "game_events": i % 4, "chat_confirmed": i % 2,
             "duration": 45, "hook_first": i % 2, "split_layout": 0}
        p = tmp_path / f"r{i}.json"
        p.write_text(json.dumps({"clip": f"c{i}", "features": f}))
        reps.append(str(p))
        views[f"c{i}"] = int(math.exp(4 + 0.08 * f["signal_bonus"] + 0.5 * f["hook_first"]))
    assert not learning.train("t", reps[:5], views)["trained"]
    r = learning.train("t", reps, views)
    assert r["trained"] and r["r2"] > 0.9
    prof = learning.load("t")
    hi = learning.adjust({"base_score": 75, "signal_bonus": 20, "hook_first": 1, "duration": 45}, prof)
    lo = learning.adjust({"base_score": 75, "signal_bonus": 0, "hook_first": 0, "duration": 45}, prof)
    assert hi > lo and -10 <= lo <= hi <= 10


# ---------------------------------------------------------------- CLI end-to-end
@pytest.mark.budget(240)
def test_cli_run_premium(media):
    r = subprocess.run([sys.executable, os.path.join(ROOT, "studio.py"), "run", media["dir"], "--tier", "premium",
                        "--cam", "1500,60,380,280", "--langs", "", "--compile", "--dry-run-schedule"],
                       capture_output=True, text=True, cwd=ROOT, env={**os.environ, "ANTHROPIC_API_KEY": ""})
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["passed"] == 2 and not out["errors"], out
    summ = json.load(open(out["summary"]))
    c1 = next(c for c in summ["clips"] if c["clip"].endswith("clip01.mp4"))
    assert c1["final"].endswith(".final.mp4") and c1["steps"]["made_by"].get("out")          # every clip ships "Made by TakeKash"
    assert c1["steps"]["split_layout"].get("out", "").endswith(".split.mp4") and "hook_first" in c1["steps"] and "brand_safe" in c1["steps"]
    assert os.path.exists(os.path.join(media["dir"], "studio", "compilation.mp4"))
