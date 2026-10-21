#!/usr/bin/env python3
"""All-In export (launch plan step 5): re-cut a finished best-windows job as 1:1 and 16:9.

  python3 lib/export_allin.py JOB                      # every window, 1:1 + 16:9
  python3 lib/export_allin.py JOB --windows 2,5        # only windows 2 and 5
  python3 lib/export_allin.py JOB --formats 1x1        # only one format

Reads   projects/JOB/best-windows/windows.json          (window start/end on the raw timeline)
        projects/JOB/raw/<video>  (re-downloaded via lib/fetch_url.py if it was pruned; or --source PATH)
        outputs/JOB_best_windows/captions/JOB_windowNN.srt  (burned in when present)
Writes  outputs/JOB_best_windows/allin/JOB_windowNN_1x1.mp4 and _16x9.mp4
The 9:16 versions your pipeline already made are untouched.
Run it through safe_run.sh like every pipeline command.
"""
import argparse, json, pathlib, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
VIDEO_EXT = {".mp4", ".mkv", ".mov", ".webm", ".m4v", ".ts", ".flv"}


def find_source(job):
    """Same lookup as the pipeline's job_raw_file (lib/common.sh): first file in
    projects/JOB/raw/ (symlinks followed, .gitkeep ignored), preferring videos."""
    raw = ROOT / "projects" / job / "raw"
    if not raw.is_dir():
        return None
    files = sorted(p for p in raw.iterdir() if p.is_file() and p.name != ".gitkeep")
    vids = [p for p in files if p.suffix.lower() in VIDEO_EXT]
    return (max(vids, key=lambda p: p.stat().st_size) if vids else None)


def _urls_near(obj, job, found):
    """Recursively collect http(s) URLs that sit in the same dict as this job name,
    or are dict keys whose value mentions the job (source_url_index.json layout)."""
    if isinstance(obj, dict):
        vals = [v for v in obj.values() if isinstance(v, str)]
        if job in vals or obj.get("job") == job:
            found += [v for v in vals if v.startswith(("http://", "https://"))]
        for k, v in obj.items():
            if isinstance(k, str) and k.startswith(("http://", "https://")) and job in json.dumps(v):
                found.append(k)
            _urls_near(v, job, found)
    elif isinstance(obj, list):
        for v in obj:
            _urls_near(v, job, found)
    return found


def find_source_url(job):
    """Where the job's video came from. Checked in order: the per-job record (raw/ or the
    copy the pruner now keeps beside it), the global source_url_index.json, .batch_state/."""
    for p in (ROOT / "projects" / job / "raw" / "source_url.json",
              ROOT / "projects" / job / "source_url.json"):
        try:
            u = json.loads(p.read_text()).get("source_url")
            if u:
                return u
        except (OSError, ValueError):
            pass
    for p in [ROOT / "source_url_index.json"] + sorted((ROOT / ".batch_state").glob("*.json")):
        try:
            hits = _urls_near(json.loads(p.read_text()), job, [])
        except (OSError, ValueError):
            continue
        if hits:
            return hits[0]
    return None


def ensure_source(job):
    """Return the raw source, re-downloading it to projects/JOB/raw/ (exactly where
    job_raw_file looks) with the pipeline's own lib/fetch_url.py if it was pruned."""
    src = find_source(job)
    if src:
        return src
    url = find_source_url(job)
    if not url:
        return None
    print(f"export_allin: raw source was pruned, re-downloading {url}", flush=True)
    subprocess.run([sys.executable, str(ROOT / "lib" / "fetch_url.py"), job, url], cwd=str(ROOT))
    return find_source(job)


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
    src = pathlib.Path(a.source).resolve() if a.source else ensure_source(a.job)
    if not src or not src.exists():
        sys.exit(f"export_allin: raw source for '{a.job}' was deleted and no source URL is on record "
                 f"(checked raw/source_url.json, source_url_index.json, .batch_state/). Pass --source FILE.")
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
