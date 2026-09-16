#!/usr/bin/env python3
"""
lib/content_graph.py
Real Content Graph queries (Layer 3).
"""
import os
import sqlite3

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT, "takekash.db")


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_clip_lineage(clip_id):
    if not os.path.exists(DB_PATH):
        return None
    conn = _connect()
    cur = conn.cursor()
    cur.execute("SELECT * FROM clips WHERE id = ?", (clip_id,))
    clip = cur.fetchone()
    if not clip:
        conn.close()
        return None
    clip = dict(clip)

    cur.execute("SELECT * FROM social_posts WHERE clip_id = ?", (clip_id,))
    posts = [dict(r) for r in cur.fetchall()]
    conn.close()

    clip["posts"] = posts
    clip["platform_count"] = len(set(p["platform"] for p in posts))
    clip["published_count"] = sum(1 for p in posts if p["status"] == "published")
    return clip


def get_source_video_summary(source_video_path):
    if not os.path.exists(DB_PATH):
        return None
    conn = _connect()
    cur = conn.cursor()
    cur.execute("SELECT id FROM clips WHERE source_video = ?", (source_video_path,))
    clip_ids = [r["id"] for r in cur.fetchall()]

    total_posts = 0
    if clip_ids:
        placeholders = ",".join("?" * len(clip_ids))
        cur.execute(f"SELECT COUNT(*) as c FROM social_posts WHERE clip_id IN ({placeholders})", clip_ids)
        total_posts = cur.fetchone()["c"]
    conn.close()

    return {
        "source_video": source_video_path,
        "real_clip_count": len(clip_ids),
        "real_post_count": total_posts,
        "real_fanout_ratio": round(total_posts / len(clip_ids), 1) if clip_ids else 0,
    }
