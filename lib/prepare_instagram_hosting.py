#!/usr/bin/env python3
"""
lib/prepare_instagram_hosting.py

Instagram's Graph API fetches each Reel FROM a public URL — it does not
accept a direct file upload the way YouTube and TikTok do (see
lib/instagram_publish.py's docstring). This pipeline only produces local
files, so something has to expose them at a real public URL first.

This script copies every pending/approved Instagram clip in
publish_schedule.json into ../takekash-site-live/clips/<content_id>.mp4
and records the resulting public URL back onto the queue item as
"public_url". lib/publish_scheduler.py's Instagram branch uses that
field instead of the local path.

IMPORTANT — this alone does not make anything live. Netlify only serves
what you've deployed. After running this, redeploy the site:

    cd ~/takekash-site-live && netlify deploy --prod

Run this BEFORE that deploy, every time new Instagram items are queued
or approved. Re-running is safe — it skips files that are already
correctly copied (same size), and only re-copies if the source changed.

Usage:
    python3 lib/prepare_instagram_hosting.py [--base-url https://takekash.com]
"""
import argparse
import json
import os
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
PIPELINE_ROOT = os.path.dirname(HERE)
QUEUE_PATH = os.path.join(PIPELINE_ROOT, "publish_schedule.json")
DEFAULT_CLIPS_DIR = os.path.normpath(
    os.path.join(PIPELINE_ROOT, "..", "takekash-site-live", "clips")
)
DEFAULT_BASE_URL = "https://takekash.com"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clips-dir", default=DEFAULT_CLIPS_DIR)
    ap.add_argument("--base-url", default=DEFAULT_BASE_URL)
    args = ap.parse_args()

    os.makedirs(args.clips_dir, exist_ok=True)

    with open(QUEUE_PATH) as f:
        items = json.load(f)

    copied, skipped_current, missing, updated = 0, 0, [], 0

    for item in items:
        if item.get("platform") != "instagram":
            continue
        if item.get("status") not in ("pending", "approved"):
            continue

        src = item.get("video_path")
        if not src or not os.path.exists(src):
            missing.append(item.get("content_id"))
            continue

        dest_name = f"{item['content_id']}.mp4"
        dest_path = os.path.join(args.clips_dir, dest_name)
        public_url = f"{args.base_url}/clips/{dest_name}"

        needs_copy = True
        if os.path.exists(dest_path):
            if os.path.getsize(dest_path) == os.path.getsize(src):
                needs_copy = False

        if needs_copy:
            shutil.copyfile(src, dest_path)
            copied += 1
        else:
            skipped_current += 1

        if item.get("public_url") != public_url:
            item["public_url"] = public_url
            updated += 1

    with open(QUEUE_PATH, "w") as f:
        json.dump(items, f, indent=2)

    print(f"Copied: {copied}, already up to date: {skipped_current}, "
          f"queue entries updated with public_url: {updated}")
    if missing:
        print(f"Skipped {len(missing)} item(s) with no resolvable video_path:")
        for c in missing:
            print(f"  - {c}")
    print()
    print("Now redeploy so these are actually reachable:")
    print("  cd ~/takekash-site-live && netlify deploy --prod")


if __name__ == "__main__":
    main()
