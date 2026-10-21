#!/usr/bin/env python3
"""GtaxZombies clip studio: stamp FREE SAMPLE watermarks on clips.

Usage:
  python3 watermark_sample.py clip1.mp4 [clip2.mp4 ...] [--out samples/] [--id LEAD-NAME]

Paid deliveries never go through this script. Only free outreach samples do.
Adds:
  1. The red GtaxZombies logo, bottom right, for the whole clip
  2. "Want the full set?" tag for the last 2.5 s -> points every viewer back to you
Each file also gets copyright metadata and a sample ID so you can trace reposts.
"""
import argparse, json, pathlib, subprocess, sys, datetime

HERE = pathlib.Path(__file__).resolve().parent
ASSETS = HERE / "assets" if (HERE / "assets").exists() else HERE  # works with or without the assets/ folder

def probe(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=width,height,codec_type",
                        "-of", "json", str(path)], capture_output=True, text=True, check=True)
    j = json.loads(r.stdout)
    v = next(s for s in j["streams"] if s["codec_type"] == "video")
    has_audio = any(s["codec_type"] == "audio" for s in j["streams"])
    return v["width"], v["height"], float(j["format"]["duration"]), has_audio

def stamp(src, outdir, sample_id):
    W, H, D, has_audio = probe(src)
    vertical = H >= W
    short = min(W, H)
    logo_w = int(W * (0.24 if vertical else 0.13)) // 2 * 2
    margin = int(short * 0.04)
    tag_w = int(W * (0.56 if vertical else 0.30)) // 2 * 2
    tag_start = max(0.0, D - 2.5)
    fc = (
        f"[1:v]scale={logo_w}:-1,format=rgba,colorchannelmixer=aa=0.92[l];"
        f"[2:v]scale={tag_w}:-1,format=rgba[t];"
        f"[0:v][l]overlay=x=W-w-{margin}:y=H-h-{margin}[v1];"
        f"[v1][t]overlay=x=(W-w)/2:y=H*0.13:enable='gte(t,{tag_start:.2f})'[v]"
    )
    out = pathlib.Path(outdir) / f"{pathlib.Path(src).stem}_FREE-SAMPLE.mp4"
    year = datetime.date.today().year
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src),
           "-loop", "1", "-i", str(ASSETS / "wm_logo_red.png"),
           "-loop", "1", "-i", str(ASSETS / "wm_endtag.png"),
           "-filter_complex", fc, "-map", "[v]"]
    if has_audio:
        cmd += ["-map", "0:a", "-c:a", "aac", "-b:a", "160k"]
    cmd += ["-c:v", "libx264", "-crf", "20", "-preset", "medium", "-pix_fmt", "yuv420p", "-shortest",
            "-movflags", "+faststart",
            "-metadata", "title=GtaxZombies clip studio - free sample",
            "-metadata", f"copyright=(c) {year} GtaxZombies. Free sample. Not licensed for reposting or resale.",
            "-metadata", f"comment=sample-id:{sample_id}",
            str(out)]
    subprocess.run(cmd, check=True)
    return out

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("clips", nargs="+")
    ap.add_argument("--out", default="samples")
    ap.add_argument("--id", default="sample", help="lead name or ID, written into the file metadata")
    a = ap.parse_args()
    for f in ("wm_logo_red.png", "wm_endtag.png"):
        if not (ASSETS / f).exists():
            sys.exit(f"Missing asset: {ASSETS / f}")
    pathlib.Path(a.out).mkdir(parents=True, exist_ok=True)
    for c in a.clips:
        print("stamped:", stamp(c, a.out, a.id))

if __name__ == "__main__":
    main()
