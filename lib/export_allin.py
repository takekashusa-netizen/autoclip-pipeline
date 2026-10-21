#!/usr/bin/env python3
"""All-In export (launch plan step 5): re-cut a finished best-windows job as 1:1 and 16:9.

  python3 lib/export_allin.py JOB                      # every window, 1:1 + 16:9
  python3 lib/export_allin.py JOB --windows 2,5        # only windows 2 and 5
  python3 lib/export_allin.py JOB --formats 1x1        # only one format

Reads   projects/JOB/best-windows/windows.json          (window start/end on the raw timeline)
        projects/JOB/raw/<largest video>                 (or --source PATH)
        outputs/JOB_best_windows/captions/JOB_windowNN.srt  (burned in when present)
Writes  outputs/JOB_best_windows/allin/JOB_windowNN_1x1.mp4 and _16x9.mp4
The 9:16 versions your pipeline already made are untouched.
Run it through safe_run.sh like every pipeline command.
"""
import argparse, json, pathlib, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
VIDEO_EXT = {".mp4", ".mkv", ".mov", ".webm", ".m4v", ".ts", ".flv"}


def find_source(job):
    raw = ROOT / "projects" / job / "raw"
    vids = [p for p in raw.glob("*") if p.suffix.lower() in VIDEO_EXT and p.is_file()] if raw.is_dir() else []
    return max(vids, key=lambda p: p.stat().st_size) if vids else None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("job")
    ap.add_argument("--windows", help="comma-separated window numbers (1-based); default all")
    ap.add_argument("--formats", default="1x1,16x9")
    ap.add_argument("--source", help="raw source video; default = largest video in projects/JOB/raw/")
    a = ap.parse_args()

    wj = ROOT / "projects" / a.job / "best-windows" / "windows.json"
    if not wj.exists():
        sys.exit(f"export_allin: no windows.json for job '{a.job}' at {wj}")
    windows = json.loads(wj.read_text())["windows"]
    src = pathlib.Path(a.source).resolve() if a.source else find_source(a.job)
    if not src or not src.exists():
        sys.exit(f"export_allin: raw source not found in {ROOT / 'projects' / a.job / 'raw'} (pass --source)")
    pick = {int(x) for x in a.windows.split(",")} if a.windows else set(range(1, len(windows) + 1))
    bad = sorted(n for n in pick if not 1 <= n <= len(windows))
    if bad:
        sys.exit(f"export_allin: job has {len(windows)} windows, no window(s) {bad}")

    out_root = ROOT / "outputs" / f"{a.job}_best_windows"
    caps = out_root / "captions"
    out = out_root / "allin"
    out.mkdir(parents=True, exist_ok=True)
    clips, missing = [], []
    for n in sorted(pick):
        w = windows[n - 1]
        name = f"{a.job}_window{n:02d}"
        clip = {"name": name, "start": float(w["start"]), "end": float(w["end"])}
        srt = caps / f"{name}.srt"
        if srt.exists():
            clip["srt"] = str(srt)
        else:
            missing.append(name)
        clips.append(clip)
    cj = out / "clips.json"
    cj.write_text(json.dumps(clips, indent=1))
    print(f"export_allin: job={a.job} source={src.name} windows={sorted(pick)} formats={a.formats}", flush=True)
    if missing:
        print(f"export_allin: no captions file for {missing} - exporting those without captions", flush=True)
    r = subprocess.run([sys.executable, str(ROOT / "export_formats.py"), str(src), str(cj),
                        "--out", str(out), "--formats", a.formats], cwd=str(ROOT))
    if r.returncode:
        sys.exit(r.returncode)
    print(f"export_allin: done -> {out}", flush=True)


if __name__ == "__main__":
    main()
