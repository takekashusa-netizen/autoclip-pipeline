#!/usr/bin/env python3
"""
lib/prune_finished_jobs.py

Reclaims disk space from projects/<job>/ once a job (or, for
clip_pipeline.sh multi-window jobs, ALL of its children) has actually
finished exporting AND its final render is confirmed sitting in
outputs/. Strips only the bulky, already-superseded intermediate media
(raw/, rough-cut/, work/, music/, music-out/, any stray .mp4 sitting
directly in graphics/) — never job.json, progress.json, thumbnail/, or
graphics-plan.json, since mcp_server.py's job-status tools and the
admin snapshot exporter still read those for finished jobs.

Confirmed via a real audit (2026-09-16): projects/ had quietly grown to
~65GB, ~38GB of which was fully-exported, fully-promoted media sitting
around for no reason — nothing in the pipeline re-reads a job's
projects/ folder once export is done; the real, final artifact is
outputs/. That one-time cleanup is done; this script is what stops it
from happening again, run automatically by dashboard.py's background
loop (see background_maintenance_loop's prune_interval_sec) as well as
callable by hand.

Safe to run any time, any frequency — idempotent, only ever removes
subdirs that are already fully superseded by a confirmed outputs/ file.

Usage:
    python3 lib/prune_finished_jobs.py [--dry-run]
"""
import argparse
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


def prune(dry_run=False):
    """Returns (freed_bytes, jobs_touched). Does the actual work."""
    job_info = _load_jobs()
    stems = _output_stems()

    def is_exported(job):
        d = job_info.get(job, {})
        return (d.get("steps", {}).get("export", {}).get("status") == "done"
                and job in stems)

    targets = []
    for j, d in job_info.items():
        if d.get("managed_by") == "clip_pipeline":
            children = [c for c in job_info if c.startswith(j + "__")]
            if children and all(is_exported(c) for c in children):
                targets.append(j)
                targets.extend(children)
        elif "__" not in j and is_exported(j):
            targets.append(j)

    # Older parent+__clipNN shape (no managed_by tag — only clip_pipeline.sh
    # sets that) is invisible to the loop above without this pass, so those
    # jobs would never get pruned. Confirmed as a real gap while building
    # disk_audit.py (2026-09-16) — same fix applied there.
    for j, d in job_info.items():
        if "__" in j and d.get("managed_by") != "clip_pipeline":
            parent = j.rsplit("__", 1)[0]
            siblings = [c for c in job_info if c.startswith(parent + "__")]
            if siblings and all(is_exported(c) for c in siblings):
                targets.append(j)

    freed = 0
    touched = 0
    for j in sorted(set(targets)):
        base = os.path.join(PROJECTS, j)
        job_freed = 0
        for sub in STRIP_SUBDIRS:
            p = os.path.join(base, sub)
            if os.path.isdir(p):
                if sub == "rough-cut":
                    # 2026-09-23: never delete rough-cut/script.json here.
                    # It's the ONLY real transcript source
                    # generate_clip_metadata.py has (no fallback exists --
                    # confirmed by reading that file in full). This dir
                    # used to get wiped the moment export finished, but
                    # metadata/caption generation can still be pending at
                    # that point, which silently and permanently broke
                    # captions for 14 real jobs the first time this ran
                    # after a restart (see CONTENT_LEDGER.md 2026-09-23).
                    # script.json is ~1KB; the real disk hog is
                    # rough_cut.mp4 and friends, which this still strips.
                    keep = os.path.join(p, "script.json")
                    for name in os.listdir(p):
                        fp = os.path.join(p, name)
                        if fp == keep:
                            continue
                        try:
                            if os.path.isdir(fp):
                                job_freed += _dir_size(fp)
                                if not dry_run:
                                    shutil.rmtree(fp, ignore_errors=True)
                            else:
                                job_freed += os.path.getsize(fp)
                                if not dry_run:
                                    os.remove(fp)
                        except OSError:
                            pass
                else:
                    job_freed += _dir_size(p)
                    if not dry_run:
                        shutil.rmtree(p, ignore_errors=True)
        gdir = os.path.join(base, "graphics")
        if os.path.isdir(gdir):
            for f in os.listdir(gdir):
                if f.endswith(".mp4"):
                    fp = os.path.join(gdir, f)
                    try:
                        job_freed += os.path.getsize(fp)
                        if not dry_run:
                            os.remove(fp)
                    except OSError:
                        pass
        if job_freed:
            freed += job_freed
            touched += 1

    return freed, touched


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    freed, touched = prune(dry_run=args.dry_run)
    verb = "would free" if args.dry_run else "freed"
    print(f"prune_finished_jobs: {verb} {freed/1e9:.2f} GB across {touched} finished job dir(s)")


if __name__ == "__main__":
    main()
