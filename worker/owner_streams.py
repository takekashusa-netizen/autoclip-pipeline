"""Clip every best moment from the owner's own past live streams, on free GitHub Actions runners.

  python worker/owner_streams.py plan            -> writes a job matrix (one entry per <=60-min chunk)
  python worker/owner_streams.py clip VID START END
                                                -> downloads that chunk, skips it if it has no real
                                                   audio, runs the clip pipeline, leaves clips in
                                                   outputs/ for the workflow to save.

Audio rule (owner's request): a chunk is clipped only when it has an audio track whose loudness
shows real sound (mean > -50 dB and peak > -30 dB). Silent or audio-less chunks are skipped and
reported, never clipped.

Only the owner's channels are read (OWNER_CHANNELS below); nothing customer-related runs here.
"""
import json
import os
import re
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECTS = os.path.join(ROOT, "projects")
OUTPUTS = os.path.join(ROOT, "outputs")
OWNER_CHANNELS = [c for c in os.environ.get(
    "OWNER_CHANNELS", "https://www.youtube.com/@gtaxzombies/streams").split(",") if c.strip()]
CHUNK = int(os.environ.get("OWNER_CHUNK_SECONDS", "3600"))
MIN_LEN = 120                  # ignore streams shorter than 2 minutes
MAX_CHUNKS = 250               # GitHub matrix ceiling is 256
VID_RE = re.compile(r"^[A-Za-z0-9_-]{6,20}$")


def log(m):
    print(f"[owner-streams] {m}", flush=True)


def ytdlp(*args, capture=True):
    return subprocess.run([sys.executable, "-m", "yt_dlp", "--no-warnings", *args],
                          capture_output=capture, text=True)


def list_streams():
    out = []
    for ch in OWNER_CHANNELS:
        r = ytdlp("--flat-playlist", "-J", ch.strip())
        if r.returncode != 0:
            log(f"could not list {ch}: {r.stderr[-300:]}")
            continue
        for e in json.loads(r.stdout).get("entries") or []:
            vid, dur = e.get("id"), int(e.get("duration") or 0)
            if vid and VID_RE.match(vid) and dur >= MIN_LEN:
                out.append({"id": vid, "title": (e.get("title") or "")[:80], "duration": dur})
    return out


def plan():
    only = os.environ.get("ONLY_VIDEOS", "").strip()
    streams = list_streams()
    if only:
        keep = {v.strip() for v in only.split(",")}
        streams = [s for s in streams if s["id"] in keep]
    matrix = []
    for s in streams:
        for start in range(0, s["duration"], CHUNK):
            end = min(start + CHUNK, s["duration"])
            if end - start < MIN_LEN and start > 0:      # fold a tiny tail into nothing
                continue
            matrix.append({"vid": s["id"], "start": start, "end": end,
                           "name": f"{s['id']}-{start // 60:04d}m"})
    matrix = matrix[:MAX_CHUNKS]
    log(f"{len(streams)} stream(s), {len(matrix)} chunk(s)")
    for s in streams:
        log(f"  {s['id']}  {s['duration'] // 60} min  {s['title']}")
    payload = json.dumps({"include": matrix})
    gh = os.environ.get("GITHUB_OUTPUT")
    if gh:
        with open(gh, "a") as f:
            f.write(f"matrix={payload}\ncount={len(matrix)}\n")
    else:
        print(payload)


def audio_ok(path):
    """True only if the file has an audio stream with real sound in it."""
    p = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries",
                        "stream=index", "-of", "csv=p=0", path], capture_output=True, text=True)
    if not p.stdout.strip():
        return False, "no audio track"
    v = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", path, "-map", "0:a:0",
                        "-af", "volumedetect", "-f", "null", "-"], capture_output=True, text=True)
    mean = re.search(r"mean_volume:\s*(-?[\d.]+|-inf)", v.stderr)
    peak = re.search(r"max_volume:\s*(-?[\d.]+|-inf)", v.stderr)
    if not mean or not peak or "inf" in mean.group(1) or "inf" in peak.group(1):
        return False, "audio track is silent"
    m, k = float(mean.group(1)), float(peak.group(1))
    if m <= -50 or k <= -30:
        return False, f"audio too quiet (mean {m} dB, peak {k} dB)"
    return True, f"audio ok (mean {m} dB, peak {k} dB)"


def clip(vid, start, end):
    if not VID_RE.match(vid):
        sys.exit("bad video id")
    start, end = int(start), int(end)
    job = f"owner-{vid}-{start // 60:04d}m".lower().replace("_", "-")
    raw_dir = os.path.join(PROJECTS, job, "raw")
    os.makedirs(raw_dir, exist_ok=True)
    src = os.path.join(raw_dir, "source.mp4")
    url = f"https://www.youtube.com/watch?v={vid}"
    log(f"{job}: downloading {start // 60}-{end // 60} min")
    r = ytdlp("-f", "bv*[height<=1080]+ba/b[height<=1080]/b", "--merge-output-format", "mp4",
              "--download-sections", f"*{start}-{end}", "--force-keyframes-at-cuts",
              "-o", src, url, capture=False)
    if r.returncode != 0 or not os.path.exists(src):
        sys.exit(f"{job}: download failed")
    ok, why = audio_ok(src)
    summary = {"job": job, "vid": vid, "start": start, "end": end, "audio": why}
    if not ok:
        log(f"{job}: SKIPPED, {why}")
        summary["clips"] = 0
        _write_summary(summary)
        return
    log(f"{job}: {why}; clipping")
    os.makedirs(OUTPUTS, exist_ok=True)
    args = [os.path.join(ROOT, "clip_pipeline.sh"), job, os.environ.get("OWNER_FORMAT", "short-tiktok-raw"),
            "--clip-length", os.environ.get("OWNER_CLIP_LENGTH", "45"),
            "--clip-count", os.environ.get("OWNER_CLIPS_PER_HOUR", "6"),
            "--bonus-clips", os.environ.get("OWNER_BONUS_CLIPS", "4"),
            "--content-type", "gaming"]
    p = subprocess.run(args, cwd=ROOT)
    files = sorted(f for f in os.listdir(OUTPUTS) if f.startswith(job + "__") and f.endswith(".final.mp4"))
    summary["clips"] = len(files)
    if p.returncode != 0 and not files:
        _write_summary(summary)
        sys.exit(f"{job}: pipeline failed")
    # keep titles/captions next to each clip if the pipeline wrote them
    for f in os.listdir(OUTPUTS):
        if f.startswith(job + "__") and not f.endswith(".final.mp4") and f.endswith((".json", ".txt", ".srt")):
            files.append(f)
    _write_summary(summary)
    log(f"{job}: {summary['clips']} clip(s)")
    shutil.rmtree(os.path.join(PROJECTS, job, "raw"), ignore_errors=True)


def _write_summary(s):
    os.makedirs(OUTPUTS, exist_ok=True)
    with open(os.path.join(OUTPUTS, f"{s['job']}__summary.json"), "w") as f:
        json.dump(s, f, indent=2)
    step = os.environ.get("GITHUB_STEP_SUMMARY")
    if step:
        with open(step, "a") as f:
            f.write(f"| {s['job']} | {s['audio']} | {s.get('clips', 0)} |\n")


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "plan":
        plan()
    elif len(sys.argv) == 5 and sys.argv[1] == "clip":
        clip(*sys.argv[2:])
    else:
        sys.exit(__doc__)
