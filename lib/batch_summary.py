#!/usr/bin/env python3
"""
lib/batch_summary.py
Real Content Factory batch report (Layer 26).
"""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def summarize_batch(job_prefix):
    queue_path = os.path.join(ROOT, "publish_schedule.json")
    with open(queue_path) as f:
        queue = json.load(f)

    job_entries = [i for i in queue if i.get("content_id", "").startswith(job_prefix)]
    tiktok_ready = [i for i in job_entries if i["platform"] == "tiktok"]
    ig_ready = [i for i in job_entries if i["platform"] == "instagram"]

    seo_scores = [i["seo_score"]["total"] for i in job_entries
                  if isinstance(i.get("seo_score"), dict)]
    high_seo = [s for s in seo_scores if s >= 90]

    return {
        "job": job_prefix,
        "total_windows_processed": len(set(i["content_id"].rsplit("_", 1)[0] for i in job_entries)),
        "tiktok_ready": len(tiktok_ready),
        "instagram_ready": len(ig_ready),
        "avg_seo_score": round(sum(seo_scores) / len(seo_scores), 1) if seo_scores else None,
        "high_seo_count": len(high_seo),
    }


def print_summary(job_prefix):
    s = summarize_batch(job_prefix)
    print(f"TakeKash processed \"{job_prefix}\":")
    print(f"  {s['total_windows_processed']} real windows extracted")
    print(f"  {s['tiktok_ready']} ready for TikTok, {s['instagram_ready']} ready for Instagram")
    if s["avg_seo_score"] is not None:
        print(f"  Average SEO score: {s['avg_seo_score']}/100 ({s['high_seo_count']} scored 90+)")


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("usage: python3 batch_summary.py <job_prefix>")
        sys.exit(1)
    print_summary(sys.argv[1])
