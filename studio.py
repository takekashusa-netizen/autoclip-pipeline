#!/usr/bin/env python3
"""GtaxZombies Clip Studio — one command for every add-on feature.

  Before selection (on the source VOD):
    studio.py signals --job JOB [--video SRC.mp4] [--game apex|warzone|nba2k|generic] [--player NAME]
                      [--chat LOG | --chat-url URL] [--region feed=x0,y0,x1,y1]
        -> projects/JOB/rough-cut/signals.json, read automatically by clip_select.py

  Per clip / per package:
    studio.py run CLIPS_DIR --tier basic|standard|premium|owner [--job JOB] [--langs es,pt] [--cam x,y,w,h]
                  [--creator gtaxzombies] [--dry-run-schedule]
    studio.py hook-first CLIP OUT [--payoff SEC] [--text "WAIT FOR IT"]
    studio.py brand-safe CLIP OUT [--mode bleep|mute] [--mute-music]
    studio.py split CLIP OUT [--cam x,y,w,h]
    studio.py podcast CLIP OUT
    studio.py translate CLIP --langs es,pt [--burn]
    studio.py thumbs CLIP OUTDIR
    studio.py compile OUT CLIP [CLIP ...] | --from-reports DIR [--days 7]
    studio.py media-kit OUT.html [--contact EMAIL]
    studio.py learn --creator NAME --reports DIR [--views views.json]
    studio.py game-events VIDEO --game apex [--player NAME] [--dump-crops DIR]
    studio.py chat LOG|URL
"""
import argparse
import glob
import json
import os
import sys
import traceback

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from studio import (active_speaker, brand_safe, chat_moments, compilation, game_events, hook_first,  # noqa: E402
                    learning, media_kit, schedule, score_report, signals, split_layout, thumbs_titles, translate)
from studio.common import StudioError, clip_stem, find_srt, probe  # noqa: E402

TIERS = json.load(open(os.path.join(ROOT, "presets", "studio-tiers.json")))


def jdump(x):
    print(json.dumps(x, indent=2, default=str))


def job_dir(job):
    return os.path.join(ROOT, "projects", job)


def cmd_signals(a):
    rough = os.path.join(job_dir(a.job), "rough-cut") if a.job else None
    video = a.video
    if not video and a.job:
        raws = sorted(glob.glob(os.path.join(job_dir(a.job), "raw", "*")))
        video = raws[0] if raws else None
    chat = None
    if a.chat:
        chat = chat_moments.detect_file(a.chat)
    elif a.chat_url:
        chat = chat_moments.fetch_and_detect(a.chat_url)
    game = None
    if video and a.game != "none":
        regions = dict(game_events.parse_region(r) for r in (a.region or []))
        game = game_events.detect(video, a.game, a.player, fps=a.fps, regions=regions or None)
    if not chat and not game:
        raise StudioError("nothing to detect: give --chat/--chat-url and/or a video")
    edl = os.path.join(rough, "edl.json") if rough else None
    sig = signals.build(chat, game, edl)
    out = a.out or (os.path.join(rough, "signals.json") if rough else "signals.json")
    signals.save(sig, out)
    jdump({"signals": out, **sig["counts"], "top": [{k: m[k] for k in ("start", "end", "score", "label")}
                                                     for m in sorted(sig["moments"], key=lambda m: -m["score"])[:8]]})


def _clips_in(d):
    files = sorted(f for f in glob.glob(os.path.join(d, "*.mp4"))
                   if not any(x in os.path.basename(f) for x in (".tmp.", ".hook.", ".safe.", ".split.", ".podcast.")))
    return files


def _clip_entry(job, stem):
    """Find this clip's selection data (clips.json) for the score report."""
    if not job:
        return {}
    p = os.path.join(job_dir(job), "rough-cut", "clips.json")
    if not os.path.exists(p):
        return {}
    clips = json.load(open(p)).get("clips", [])
    for c in clips:
        if c["id"] in stem or stem.endswith(c["id"]):
            return c
    return {}


def cmd_run(a):
    tier = TIERS[a.tier]
    feats = set(tier["features"])
    gate = a.gate or tier["gate"]
    clips = _clips_in(a.clips_dir)
    if not clips:
        raise StudioError(f"no .mp4 clips in {a.clips_dir}")
    sig = signals.Signals.load(os.path.join(job_dir(a.job), "rough-cut", "signals.json")) if a.job else None
    profile = learning.load(a.creator) if "learning" in feats else None
    summary = {"tier": a.tier, "price_usd": tier["price_usd"], "gate": gate, "clips": []}
    passed = []
    for clip in clips:
        stem = clip_stem(clip)
        od = os.path.join(a.clips_dir, "studio", stem)
        os.makedirs(od, exist_ok=True)
        res = {"clip": clip, "out_dir": od, "steps": {}}

        def step(name, fn):
            try:
                res["steps"][name] = fn()
            except Exception as e:  # one failed add-on never sinks the rest of the package
                res["steps"][name] = {"error": str(e)[:400]}
                if os.environ.get("STUDIO_DEBUG"):
                    traceback.print_exc()

        entry = _clip_entry(a.job, stem)
        if not entry:
            entry = {"start": 0, "end": probe(clip)["duration"], "engagement_score": a.default_score}
        rep = score_report.build(stem, entry, sig.moments if sig else None, gate,
                                 extras={"source_clip": os.path.abspath(clip), "tier": a.tier})
        if profile:
            nudge = learning.adjust(rep["features"], profile)
            rep["learned_adjustment"] = nudge
            rep["score"] = max(0, min(100, rep["score"] + nudge))
            rep["decision"] = "PASS" if rep["score"] >= gate else "HOLD"
        if "score_report" in feats:
            score_report.write(rep, od)
        res["score"], res["decision"] = rep["score"], rep["decision"]
        if rep["decision"] != "PASS" and not a.ignore_gate:
            res["steps"]["skipped"] = f"held by {gate}+ gate (score {rep['score']})"
            summary["clips"].append(res)
            continue
        working = clip
        payoff_times = []
        if sig and entry:
            payoff_times = [m["peak_t"] - entry.get("start", 0) for m in sig.moments
                            if entry.get("start", 0) <= m.get("peak_t", -1) <= entry.get("end", 0)]
        if "brand_safe" in feats:
            out = os.path.join(od, f"{stem}.safe.mp4")
            step("brand_safe", lambda: brand_safe.make(working, out))
            if res["steps"]["brand_safe"].get("out"):
                working = out
        if "hook_first" in feats:
            out = os.path.join(od, f"{stem}.hook.mp4")
            step("hook_first", lambda: hook_first.make(working, out, signal_times=payoff_times))
            if res["steps"]["hook_first"].get("out"):
                working = out
                rep["features"]["hook_first"] = 1
        if "split_layout" in feats and (a.cam or a.auto_cam):
            info = probe(working)
            if info["width"] > info["height"]:
                out = os.path.join(od, f"{stem}.split.mp4")
                step("split_layout", lambda: split_layout.make(working, out, cam=a.cam))
                if res["steps"]["split_layout"].get("out"):
                    working = out
                    rep["features"]["split_layout"] = 1
        if "podcast" in feats and a.podcast:
            out = os.path.join(od, f"{stem}.podcast.mp4")
            step("podcast", lambda: active_speaker.make(clip, out))
            if res["steps"]["podcast"].get("out"):
                working = out
        titles = []
        if "thumbs_titles" in feats:
            step("thumbs_titles", lambda: thumbs_titles.make(working, od, around=(payoff_times or [None])[0],
                                                             labels=[m for m in rep["reasons"]]))
            titles = res["steps"]["thumbs_titles"].get("titles", [])
        if "translate" in feats and a.langs:
            srt = find_srt(clip)
            if srt:
                step("translate", lambda: translate.make(clip, a.langs.split(","), srt=srt, out_dir=od))
            else:
                res["steps"]["translate"] = {"skipped": "no SRT for this clip"}
        if "schedule" in feats:
            step("schedule", lambda: schedule.queue(working, titles, dry_run=a.dry_run_schedule))
        if "score_report" in feats:
            score_report.write(rep, od)          # rewrite with final features (hook/split) for the learning loop
        res["final"] = working
        passed.append((working, rep["score"]))
        summary["clips"].append(res)
    if "compilation" in feats and len(passed) >= 2 and a.compile:
        out = os.path.join(a.clips_dir, "studio", "compilation.mp4")
        try:
            summary["compilation"] = compilation.build(passed, out)
        except Exception as e:
            summary["compilation"] = {"error": str(e)[:400]}
    if "media_kit" in feats and a.media_kit:
        summary["media_kit"] = media_kit.render(media_kit.gather(), os.path.join(a.clips_dir, "studio", "media-kit.html"))
    if "learning" in feats:
        reports = glob.glob(os.path.join(a.clips_dir, "studio", "*", "report.json"))
        summary["learning"] = learning.train(a.creator, reports)
    json.dump(summary, open(os.path.join(a.clips_dir, "studio", "summary.json"), "w"), indent=2, default=str)
    jdump({"tier": a.tier, "clips": len(clips), "passed": len(passed),
           "held": sum(1 for c in summary["clips"] if c.get("decision") == "HOLD"),
           "errors": {c["clip"]: {k: v["error"] for k, v in c["steps"].items() if isinstance(v, dict) and "error" in v}
                      for c in summary["clips"] if any(isinstance(v, dict) and "error" in v for v in c["steps"].values())},
           "summary": os.path.join(a.clips_dir, "studio", "summary.json")})


def main():
    p = argparse.ArgumentParser(description="GtaxZombies Clip Studio")
    sp = p.add_subparsers(dest="cmd", required=True)
    s = sp.add_parser("signals")
    s.add_argument("--job")
    s.add_argument("--video")
    s.add_argument("--game", default="generic", choices=list(game_events.PROFILES) + ["none"])
    s.add_argument("--player", default=os.environ.get("STUDIO_PLAYER", "GtaxZombies"))
    s.add_argument("--chat")
    s.add_argument("--chat-url")
    s.add_argument("--region", action="append")
    s.add_argument("--fps", type=float, default=1.0)
    s.add_argument("--out")
    r = sp.add_parser("run")
    r.add_argument("clips_dir")
    r.add_argument("--tier", default="standard", choices=list(k for k in TIERS if not k.startswith("_")))
    r.add_argument("--job")
    r.add_argument("--gate", type=int)
    r.add_argument("--ignore-gate", action="store_true")
    r.add_argument("--default-score", type=int, default=90,
                   help="score for clips with no clips.json entry (already hand-picked)")
    r.add_argument("--langs", default="es,pt")
    r.add_argument("--cam")
    r.add_argument("--auto-cam", action="store_true")
    r.add_argument("--podcast", action="store_true")
    r.add_argument("--compile", action="store_true")
    r.add_argument("--media-kit", action="store_true")
    r.add_argument("--creator", default="gtaxzombies")
    r.add_argument("--dry-run-schedule", action="store_true")
    for name, n in (("hook-first", 2), ("brand-safe", 2), ("split", 2), ("podcast", 2)):
        x = sp.add_parser(name)
        x.add_argument("clip")
        x.add_argument("out")
        if name == "hook-first":
            x.add_argument("--payoff", type=float)
            x.add_argument("--text")
        if name == "brand-safe":
            x.add_argument("--mode", default="bleep", choices=["bleep", "mute"])
            x.add_argument("--mute-music", action="store_true")
        if name == "split":
            x.add_argument("--cam")
    t = sp.add_parser("translate")
    t.add_argument("clip")
    t.add_argument("--langs", required=True)
    t.add_argument("--burn", action="store_true")
    th = sp.add_parser("thumbs")
    th.add_argument("clip")
    th.add_argument("outdir")
    c = sp.add_parser("compile")
    c.add_argument("out")
    c.add_argument("clips", nargs="*")
    c.add_argument("--from-reports")
    c.add_argument("--days", type=int, default=7)
    mk = sp.add_parser("media-kit")
    mk.add_argument("out")
    mk.add_argument("--contact")
    le = sp.add_parser("learn")
    le.add_argument("--creator", default="gtaxzombies")
    le.add_argument("--reports", required=True)
    le.add_argument("--views")
    ge = sp.add_parser("game-events")
    ge.add_argument("video")
    ge.add_argument("--game", default="generic", choices=list(game_events.PROFILES))
    ge.add_argument("--player")
    ge.add_argument("--fps", type=float, default=1.0)
    ge.add_argument("--dump-crops")
    ch = sp.add_parser("chat")
    ch.add_argument("src")
    a = p.parse_args()

    try:
        if a.cmd == "signals":
            cmd_signals(a)
        elif a.cmd == "run":
            cmd_run(a)
        elif a.cmd == "hook-first":
            jdump(hook_first.make(a.clip, a.out, a.payoff, tease_text=a.text))
        elif a.cmd == "brand-safe":
            jdump(brand_safe.make(a.clip, a.out, a.mode, mute_music=a.mute_music))
        elif a.cmd == "split":
            jdump(split_layout.make(a.clip, a.out, a.cam))
        elif a.cmd == "podcast":
            jdump(active_speaker.make(a.clip, a.out))
        elif a.cmd == "translate":
            jdump(translate.make(a.clip, a.langs.split(","), burn=a.burn))
        elif a.cmd == "thumbs":
            jdump(thumbs_titles.make(a.clip, a.outdir))
        elif a.cmd == "compile":
            items = compilation.from_reports([a.from_reports], a.days) if a.from_reports else [(c, 0) for c in a.clips]
            jdump(compilation.build(items, a.out))
        elif a.cmd == "media-kit":
            jdump({"out": media_kit.render(media_kit.gather(), a.out, contact=a.contact)})
        elif a.cmd == "learn":
            views = json.load(open(a.views)) if a.views else None
            jdump(learning.train(a.creator, glob.glob(os.path.join(a.reports, "**", "report.json"), recursive=True), views))
        elif a.cmd == "game-events":
            jdump(game_events.detect(a.video, a.game, a.player, fps=a.fps, dump_dir=a.dump_crops))
        elif a.cmd == "chat":
            jdump(chat_moments.fetch_and_detect(a.src) if a.src.startswith("http") else chat_moments.detect_file(a.src))
    except StudioError as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
