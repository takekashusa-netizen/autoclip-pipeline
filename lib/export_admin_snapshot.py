#!/usr/bin/env python3
"""
lib/export_admin_snapshot.py

Exports a single JSON snapshot of the pipeline's real state (jobs,
publish queue, recent social posts) for the takekash.com admin
dashboard. The site is static (Netlify, no live backend reachable
from your Mac), so the dashboard doesn't query this data live — it
reads whatever snapshot was baked into the admin function at the
last deploy.

Usage (run this from the autoclip-pipeline folder on your Mac,
whenever you want the admin dashboard to reflect current data):

    python3 lib/export_admin_snapshot.py

Then redeploy the site (see ADMIN-SETUP.txt in takekash-site-live)
so the new snapshot actually goes live. Re-running this script alone
does NOT update the live dashboard by itself.

Writes to ../takekash-site-live/netlify/functions/admin-data/snapshot.json
by default (siblings on disk, per the real folder layout on this Mac).
Override with --out if that ever changes.
"""
import argparse
import json
import os
import re
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
PIPELINE_ROOT = os.path.dirname(HERE)
DB_PATH = os.path.join(PIPELINE_ROOT, "takekash.db")
QUEUE_PATH = os.path.join(PIPELINE_ROOT, "publish_schedule.json")
DEFAULT_OUT = os.path.normpath(
    os.path.join(PIPELINE_ROOT, "..", "takekash-site-live",
                 "netlify", "functions", "admin-data", "snapshot.json")
)

JOB_SUFFIX_RE = re.compile(r"_(best_windows|vertical|windows)$")


def clean_job_label(dirname):
    return JOB_SUFFIX_RE.sub("", dirname)


def build_jobs(cur):
    cur.execute("select source_video, game, status, created_at from clips")
    rows = cur.fetchall()
    jobs = defaultdict(lambda: {
        "job_id": None, "game": None, "clip_count": 0,
        "status_counts": defaultdict(int),
        "first_created_at": None, "last_created_at": None,
    })
    for source_video, game, status, created_at in rows:
        dirname = os.path.basename(os.path.dirname(source_video or ""))
        job_id = clean_job_label(dirname) if dirname else "unknown"
        j = jobs[job_id]
        j["job_id"] = job_id
        if game and not j["game"]:
            j["game"] = game
        j["clip_count"] += 1
        j["status_counts"][status or "unknown"] += 1
        if created_at:
            if not j["first_created_at"] or created_at < j["first_created_at"]:
                j["first_created_at"] = created_at
            if not j["last_created_at"] or created_at > j["last_created_at"]:
                j["last_created_at"] = created_at
    out = []
    for j in jobs.values():
        j["status_counts"] = dict(j["status_counts"])
        out.append(j)
    out.sort(key=lambda j: j["last_created_at"] or "", reverse=True)
    return out


def build_posts(cur):
    cur.execute("""select platform, title, status, scheduled_for, published_at,
                          created_at from social_posts""")
    rows = cur.fetchall()
    by_status = defaultdict(int)
    by_platform = defaultdict(int)
    recent = []
    for platform, title, status, scheduled_for, published_at, created_at in rows:
        by_status[status or "unknown"] += 1
        by_platform[platform or "unknown"] += 1
        recent.append({
            "platform": platform, "title": title, "status": status,
            "scheduled_for": scheduled_for, "published_at": published_at,
            "created_at": created_at,
        })
    recent.sort(key=lambda p: p["created_at"] or "", reverse=True)
    return {
        "by_status": dict(by_status),
        "by_platform": dict(by_platform),
        "total": len(rows),
        "recent": recent[:25],
    }


def build_queue():
    if not os.path.exists(QUEUE_PATH):
        return {"pending_count": 0, "approved_count": 0, "upcoming": [], "total": 0}
    with open(QUEUE_PATH) as f:
        items = json.load(f)
    status_counts = defaultdict(int)
    for it in items:
        status_counts[it.get("status", "unknown")] += 1
    upcoming = sorted(
        [it for it in items if it.get("status") in ("pending", "approved")],
        key=lambda it: it.get("scheduled_time") or "",
    )
    return {
        "status_counts": dict(status_counts),
        "total": len(items),
        "upcoming": [
            {
                "platform": it.get("platform"),
                "content_id": it.get("content_id"),
                "title": it.get("title"),
                "scheduled_time": it.get("scheduled_time"),
                "status": it.get("status"),
                "seo_total": (it.get("seo_score") or {}).get("total"),
            }
            for it in upcoming[:40]
        ],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=DEFAULT_OUT)
    args = ap.parse_args()

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    snapshot = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "jobs": build_jobs(cur),
        "posts": build_posts(cur),
        "queue": build_queue(),
    }
    snapshot["totals"] = {
        "clips": sum(j["clip_count"] for j in snapshot["jobs"]),
        "social_posts": snapshot["posts"]["total"],
        "queue_items": snapshot["queue"]["total"],
    }

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(snapshot, f, indent=2)

    print(f"Wrote snapshot to {args.out}")
    print(f"  jobs: {len(snapshot['jobs'])}, clips: {snapshot['totals']['clips']}, "
          f"social_posts: {snapshot['totals']['social_posts']}, "
          f"queue_items: {snapshot['totals']['queue_items']}")


if __name__ == "__main__":
    main()
