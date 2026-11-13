"""Scheduled auto-posting: queue each finished clip to every platform at the
next open research-backed slot (lib/publish_scheduler.py does slots, retries
and the actual posting; Metricool/YouTube/TikTok/IG publishers stay as-is)."""
import os
import sys

from .common import ROOT, clip_stem

sys.path.insert(0, os.path.join(ROOT, "lib"))

PLATFORMS = ["tiktok", "youtube", "instagram"]


def queue(clip, titles, platforms=None, description="", tags=None, content_type="gaming", dry_run=False):
    platforms = platforms or PLATFORMS
    out = []
    for i, p in enumerate(platforms):
        title = titles[i % len(titles)] if titles else clip_stem(clip)
        item = {"platform": p, "content_id": f"{clip_stem(clip)}_{p}", "video_path": os.path.abspath(clip),
                "title": title}
        if not dry_run:
            import publish_scheduler
            res = publish_scheduler.enqueue(p, item["content_id"], item["video_path"], title, description,
                                            tags or [], content_type)
            item["scheduled"] = res
        out.append(item)
    return out
