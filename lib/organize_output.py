#!/usr/bin/env python3
"""
lib/organize_output.py <job> [--title "video title"] [--date YYYY-MM-DD]

Moves outputs/<job>.final.mp4 or outputs/<job>__clip*.final.mp4 into
outputs/clips/<date>_<title-slug>/01.mp4, 02.mp4, ... — so finished clips
are organized by when/what instead of an opaque job hash.

If --title isn't given, tries to read it from the job's job.json (which
fetch_url.py doesn't currently store there — pass --title explicitly from
the watcher, which does have it from yt-dlp's metadata).
"""
import argparse
import json
import os
import re
import shutil
import sys
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUTS = os.path.join(ROOT, "outputs")


def slugify(text, max_len=60):
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = text.strip("-")
    return text[:max_len] or "untitled"


def find_outputs(job):
    single = os.path.join(OUTPUTS, f"{job}.final.mp4")
    if os.path.exists(single):
        return [single]
    prefix = f"{job}__"
    if not os.path.isdir(OUTPUTS):
        return []
    return sorted(
        os.path.join(OUTPUTS, f)
        for f in os.listdir(OUTPUTS)
        if f.startswith(prefix) and f.endswith(".final.mp4")
    )


def main():
    p = argparse.ArgumentParser()
    p.add_argument("job")
    p.add_argument("--title", default=None)
    p.add_argument("--date", default=None)
    args = p.parse_args()

    files = find_outputs(args.job)
    if not files:
        print(json.dumps({"error": f"no finished outputs found for job {args.job}"}))
        sys.exit(1)

    day = args.date or date.today().isoformat()
    slug = slugify(args.title or args.job)
    dest_dir = os.path.join(OUTPUTS, "clips", f"{day}_{slug}")
    os.makedirs(dest_dir, exist_ok=True)

    moved = []
    for i, f in enumerate(files, start=1):
        dest = os.path.join(dest_dir, f"{i:02d}.mp4")
        shutil.move(f, dest)
        moved.append(dest)

    manifest = {
        "job": args.job,
        "title": args.title,
        "date": day,
        "clip_count": len(moved),
    }
    with open(os.path.join(dest_dir, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)

    print(json.dumps({"dest_dir": dest_dir, "files": moved}))


if __name__ == "__main__":
    main()
