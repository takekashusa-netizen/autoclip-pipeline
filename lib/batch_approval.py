#!/usr/bin/env python3
"""
lib/batch_approval.py
Real Smart Batch Approval (Layer 27).
"""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QUEUE_PATH = os.path.join(ROOT, "publish_schedule.json")


def _load_queue():
    with open(QUEUE_PATH) as f:
        return json.load(f)


def _save_queue(queue):
    with open(QUEUE_PATH, "w") as f:
        json.dump(queue, f, indent=2)


def _seo_total(item):
    score = item.get("seo_score")
    return score.get("total", 0) if isinstance(score, dict) else 0


def approve_all(job_prefix=None):
    queue = _load_queue()
    count = 0
    for item in queue:
        if item["status"] != "pending":
            continue
        if job_prefix and not item.get("content_id", "").startswith(job_prefix):
            continue
        item["status"] = "approved"
        count += 1
    _save_queue(queue)
    return count


def reject_all(job_prefix=None):
    queue = _load_queue()
    count = 0
    for item in queue:
        if item["status"] != "pending":
            continue
        if job_prefix and not item.get("content_id", "").startswith(job_prefix):
            continue
        item["status"] = "rejected"
        count += 1
    _save_queue(queue)
    return count


def approve_top_n(n, job_prefix=None):
    queue = _load_queue()
    candidates = [i for i in queue if i["status"] == "pending"
                  and (not job_prefix or i.get("content_id", "").startswith(job_prefix))]
    candidates.sort(key=_seo_total, reverse=True)
    approved_ids = set(id(c) for c in candidates[:n])
    count = 0
    for item in queue:
        if id(item) in approved_ids:
            item["status"] = "approved"
            count += 1
    _save_queue(queue)
    return count


def approve_above_score(min_score, job_prefix=None):
    queue = _load_queue()
    count = 0
    for item in queue:
        if item["status"] != "pending":
            continue
        if job_prefix and not item.get("content_id", "").startswith(job_prefix):
            continue
        if _seo_total(item) >= min_score:
            item["status"] = "approved"
            count += 1
    _save_queue(queue)
    return count


def flagged_only(job_prefix=None, threshold=85):
    queue = _load_queue()
    return [i for i in queue if i["status"] == "pending"
            and (not job_prefix or i.get("content_id", "").startswith(job_prefix))
            and _seo_total(i) < threshold]
