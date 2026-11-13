"""Weekly long-form compilation: the week's best clips -> one 16:9 YouTube video.

Order: 2nd-best opens (strong start), the rest build up, the best closes.
Every clip is normalised to 1920x1080/30fps/48 kHz (vertical clips sit on a
blurred fill), loudness-normalised, and preceded by a 1.2 s brand number card.
Chapters are written for the description; YouTube only shows them when every
chapter is >= 10 s, so cards are folded into the following clip's chapter.
"""
import json
import os
import shutil
import tempfile

from .common import AUDIO_ENC, VIDEO_ENC, StudioError, clip_stem, ff_escape, ffmpeg, font, probe, run

W, H, FPS = 1920, 1080, 30
CARD = 1.2


def order(clips):
    """clips: [(path, score)] -> playback order."""
    s = sorted(clips, key=lambda c: -c[1])
    if len(s) < 3:
        return list(reversed(s))
    best, second, rest = s[0], s[1], s[2:]
    return [second] + sorted(rest, key=lambda c: c[1]) + [best]


def _norm(src, dst):
    info = probe(src)
    if info["width"] / info["height"] < 1.5:   # vertical/square: blurred fill
        vf = (f"[0:v]split[a][b];[a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=40:2,"
              f"eq=brightness=-0.15[bg];[b]scale=-2:{H}[fg];[bg][fg]overlay=(W-w)/2:0,fps={FPS},setsar=1[v]")
    else:
        vf = f"[0:v]scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,fps={FPS},setsar=1[v]"
    if info["has_audio"]:
        ffmpeg(["-i", src, "-filter_complex", vf + ";[0:a]loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000[a]",
                "-map", "[v]", "-map", "[a]"] + VIDEO_ENC + AUDIO_ENC + ["-ac", "2"], dst)
    else:
        ffmpeg(["-i", src, "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-filter_complex", vf, "-map", "[v]",
                "-map", "1:a", "-shortest"] + VIDEO_ENC + AUDIO_ENC, dst)
    return probe(dst)["duration"]


def _card(n, label, dst):
    big, small = font("Black"), font("Medium")
    vf = (f"drawbox=x=0:y=ih/2+150:w=iw*min(t/{CARD * 0.6:.2f}\\,1):h=8:color=0xE8452F:t=fill,"
          f"drawtext=fontfile='{big}':text='#{n}':fontsize=260:fontcolor=0xE8452F:x=(w-tw)/2:y=(h-th)/2-60,"
          f"drawtext=fontfile='{small}':text='{ff_escape(label[:60].upper())}':fontsize=44:fontcolor=0xF4F5F2:"
          f"x=(w-tw)/2:y=h/2+190,fade=t=in:st=0:d=0.15,fade=t=out:st={CARD - 0.15:.2f}:d=0.15")
    ffmpeg(["-f", "lavfi", "-i", f"color=c=0x0E1114:s={W}x{H}:r={FPS}:d={CARD}", "-f", "lavfi", "-i",
            "anullsrc=r=48000:cl=stereo", "-vf", vf, "-t", f"{CARD}"] + VIDEO_ENC + AUDIO_ENC, dst)


def build(clips, out, labels=None, title="Best of the week"):
    """clips: [(path, score)]. Returns {out, chapters_text, duration}."""
    if len(clips) < 2:
        raise StudioError("need at least 2 clips for a compilation")
    seq = order(clips)
    work = tempfile.mkdtemp(prefix="comp_")
    parts, chapters, t = [], [], 0.0
    try:
        n = len(seq)
        for i, (path, score) in enumerate(seq):
            label = (labels or {}).get(path) or clip_stem(path).replace("_", " ")
            card = os.path.join(work, f"{i:03d}_card.mp4")
            body = os.path.join(work, f"{i:03d}_clip.mp4")
            _card(n - i, label, card)
            d = _norm(path, body)
            chapters.append((t, f"#{n - i} {label}"))
            parts += [card, body]
            t += CARD + d
        lst = os.path.join(work, "list.txt")
        open(lst, "w").write("".join(f"file '{p}'\n" for p in parts))
        ffmpeg(["-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", "-movflags", "+faststart"], out)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    # YouTube chapter rules: first at 0:00, >= 3 chapters, each >= 10 s
    ok = [c for c in chapters]
    merged = []
    for st, name in ok:
        if merged and st - merged[-1][0] < 10:
            continue
        merged.append((st, name))
    lines = [f"{int(s // 60)}:{int(s % 60):02d} {name}" for s, name in merged]
    if lines:
        lines[0] = "0:00 " + lines[0].split(" ", 1)[1]
    return {"out": out, "duration": round(t, 2), "order": [p for p, _ in seq],
            "chapters_text": "\n".join(lines) if len(lines) >= 3 else "", "title": title}


def from_reports(clip_dirs, since_days=7, top=10):
    """Pick clips from studio report.json files (score + age)."""
    import time
    cutoff = time.time() - since_days * 86400
    found = []
    for d in clip_dirs:
        for root, _, files in os.walk(d):
            if "report.json" in files:
                rep = json.load(open(os.path.join(root, "report.json")))
                src = rep.get("source_clip")
                if src and os.path.exists(src) and os.path.getmtime(src) >= cutoff:
                    found.append((src, rep.get("score", 0)))
    found.sort(key=lambda c: -c[1])
    return found[:top]
