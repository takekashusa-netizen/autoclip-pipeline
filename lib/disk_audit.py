#!/usr/bin/env python3
"""
lib/disk_audit.py

One-shot disk audit for autoclip-pipeline. Consolidates what used to
take ~15 separate manual investigation steps (the 2026-09-16 audit) into
a single script: classifies every projects/<job> dir (RECLAIMABLE /
NEEDED / ABANDONED — see the class docstrings below), sizes up dead
scaffolding (.bak files, __pycache__, .DS_Store), and reports it all in
one pass. Pair with lib/prune_finished_jobs.py, which already runs this
same RECLAIMABLE logic automatically every day from dashboard.py — this
script exists for everything that automatic pass does NOT cover:
zero-clip abandoned trial runs and scaffolding clutter, plus a quick
report of what prune_finished_jobs would find right now.

RECLAIMABLE: job fully exported AND its final render is confirmed
  actually sitting in outputs/ (checked against the real file, not just
  job.json's status field). Safe to strip raw/rough-cut/work/music
  media from — job.json/progress.json/thumbnail are always kept, since
  mcp_server.py's job-status tools and export_admin_snapshot.py still
  read those after export.
NEEDED: not yet exported, or exported but not yet confirmed in
  outputs/. Never touched.
ABANDONED: a clip_pipeline.sh parent job (managed_by: clip_pipeline)
  that downloaded a full source video and started, but never produced
  a single child clip. A judgment call, not an automatic deletion —
  requires --yes-abandoned even with --clean.

Usage:
    python3 lib/disk_audit.py                         # report only
    python3 lib/disk_audit.py --clean                  # deletes RECLAIMABLE media + scaffolding clutter
    python3 lib/disk_audit.py --clean --yes-abandoned   # also deletes ABANDONED job dirs entirely
"""
import argparse
import glob
import json
import os
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PROJECTS = os.path.join(ROOT, "projects")
OUTPUTS = os.path.join(ROOT, "outputs")
STRIP_SUBDIRS = ["raw", "rough-cut", "work", "music", "music-out"]


def _dir_size(path):
    total = 0
    for r, _, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(r, f))
            except OSError:
                pass
    return total


def _file_size(path):
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def _load_jobs():
    info = {}
    if not os.path.isdir(PROJECTS):
        return info
    for j in os.listdir(PROJECTS):
        jp = os.path.join(PROJECTS, j, "job.json")
        if os.path.isfile(jp):
            try:
                info[j] = json.load(open(jp))
            except Exception:
                info[j] = {}
    return info


def _output_stems():
    stems = set()
    if not os.path.isdir(OUTPUTS):
        return stems
    for r, _, files in os.walk(OUTPUTS):
        for f in files:
            if f.endswith(".final.mp4"):
                stems.add(f[: -len(".final.mp4")])
    return stems


def classify():
    job_info = _load_jobs()
    stems = _output_stems()

    def is_exported(job):
        d = job_info.get(job, {})
        return (d.get("steps", {}).get("export", {}).get("status") == "done"
                and job in stems)

    reclaimable, needed, abandoned = [], [], []
    for j, d in job_info.items():
        is_parent = d.get("managed_by") == "clip_pipeline"
        children = [c for c in job_info if c.startswith(j + "__")]
        base = os.path.join(PROJECTS, j)
        if is_parent:
            if not children:
                abandoned.append((j, _dir_size(base)))
            elif all(is_exported(c) for c in children):
                reclaimable.append(j)
                reclaimable.extend(children)
            else:
                needed.append(j)
        elif "__" not in j:
            (reclaimable if is_exported(j) else needed).append(j)

    # Older parent+__clipNN shape (e.g. b951cc787dc7) never gets a
    # managed_by tag — only clip_pipeline.sh sets that. Without this pass
    # those children are invisible to the loop above and never reclaimed.
    for j, d in job_info.items():
        if "__" in j and d.get("managed_by") != "clip_pipeline":
            parent = j.rsplit("__", 1)[0]
            siblings = [c for c in job_info if c.startswith(parent + "__")]
            if siblings and all(is_exported(c) for c in siblings):
                reclaimable.append(j)
            elif j not in reclaimable:
                needed.append(j)
    return sorted(set(reclaimable)), sorted(set(needed) - set(reclaimable)), abandoned


def scaffold_items():
    """Mechanically-safe clutter only — .bak/__pycache__/.DS_Store.
    Dead one-off logs need eyeballing (recency + whether a live process
    still writes them) so they're deliberately NOT auto-detected here;
    see the autoclip-pipeline-disk-cleanup skill for that manual step."""
    items = []  # (label, path, size_bytes, is_dir)
    for pat in ("*.bak", "*.bak2"):
        for p in glob.glob(os.path.join(ROOT, pat)):
            items.append(("bak", p, _file_size(p), False))
    for p in (os.path.join(ROOT, "__pycache__"), os.path.join(ROOT, "lib", "__pycache__")):
        if os.path.isdir(p):
            items.append(("pycache", p, _dir_size(p), True))
    ds = os.path.join(ROOT, ".DS_Store")
    if os.path.isfile(ds):
        items.append(("dsstore", ds, _file_size(ds), False))
    return items


def strip_job_media(job, dry_run=True):
    base = os.path.join(PROJECTS, job)
    freed = 0
    for sub in STRIP_SUBDIRS:
        p = os.path.join(base, sub)
        if os.path.isdir(p):
            freed += _dir_size(p)
            if not dry_run:
                shutil.rmtree(p, ignore_errors=True)
    gdir = os.path.join(base, "graphics")
    if os.path.isdir(gdir):
        for f in os.listdir(gdir):
            if f.endswith(".mp4"):
                fp = os.path.join(gdir, f)
                freed += _file_size(fp)
                if not dry_run:
                    try:
                        os.remove(fp)
                    except OSError:
                        pass
    return freed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clean", action="store_true",
                     help="actually delete reclaimable media + scaffolding clutter")
    ap.add_argument("--yes-abandoned", action="store_true",
                     help="also delete ABANDONED (zero-clip trial run) job dirs entirely — requires --clean")
    args = ap.parse_args()

    reclaimable, needed, abandoned = classify()
    scaffold = scaffold_items()
    reclaimable_bytes = sum(_dir_size(os.path.join(PROJECTS, j)) for j in reclaimable)
    abandoned_bytes = sum(sz for _, sz in abandoned)
    scaffold_bytes = sum(sz for _, _, sz, _ in scaffold)

    print(f"RECLAIMABLE: {len(reclaimable)} job dir(s), ~{reclaimable_bytes/1e9:.2f} GB of media on disk right now")
    print(f"NEEDED (left alone): {len(needed)} job dir(s)")
    print(f"ABANDONED zero-clip trial runs: {len(abandoned)} job dir(s), {abandoned_bytes/1e9:.2f} GB")
    for j, sz in sorted(abandoned, key=lambda x: -x[1]):
        print(f"    {j:30s} {sz/1e9:.2f} GB")
    print(f"SCAFFOLDING CLUTTER: {len(scaffold)} item(s), {scaffold_bytes/1e6:.1f} MB")
    for label, p, sz, _ in scaffold:
        print(f"    [{label}] {os.path.relpath(p, ROOT):40s} {sz/1e6:.1f} MB")

    if not args.clean:
        print("\n(report only — pass --clean to delete reclaimable media + scaffolding; "
              "add --yes-abandoned to also clear the zero-clip trial runs above)")
        return

    freed = 0
    for j in reclaimable:
        freed += strip_job_media(j, dry_run=False)
    for label, p, sz, is_dir in scaffold:
        try:
            if is_dir:
                shutil.rmtree(p, ignore_errors=True)
            else:
                os.remove(p)
        except OSError:
            pass
        freed += sz
    if args.yes_abandoned:
        for j, sz in abandoned:
            shutil.rmtree(os.path.join(PROJECTS, j), ignore_errors=True)
            freed += sz
    print(f"\nFreed: {freed/1e9:.2f} GB")


if __name__ == "__main__":
    main()
