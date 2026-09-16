#!/usr/bin/env python3
"""
lib/performance_analytics.py
Real Performance Analytics + Learning Loop (Layers 20-21, 28, 30, 33-34).
"""
import os
import sqlite3

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT, "takekash.db")


def record_analytics(social_post_id, views=0, likes=0, comments=0, shares=0,
                      watch_time_sec=None, completion_rate=None, followers_gained=0):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        INSERT INTO analytics (social_post_id, views, likes, comments, shares,
                                watch_time_sec, completion_rate, followers_gained)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (social_post_id, views, likes, comments, shares, watch_time_sec, completion_rate, followers_gained))
    conn.commit()
    conn.close()


def top_performing_clips(limit=10):
    if not os.path.exists(DB_PATH):
        return []
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("""
        SELECT c.id, c.game, sp.platform, sp.title, SUM(a.views) as total_views,
               SUM(a.likes) as total_likes
        FROM analytics a
        JOIN social_posts sp ON sp.id = a.social_post_id
        JOIN clips c ON c.id = sp.clip_id
        GROUP BY sp.id
        ORDER BY total_views DESC
        LIMIT ?
    """, (limit,))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def best_performing_hashtags(min_posts=3):
    if not os.path.exists(DB_PATH):
        return {"note": "no database yet"}
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("""
        SELECT sp.hashtags, a.views
        FROM analytics a JOIN social_posts sp ON sp.id = a.social_post_id
    """)
    rows = cur.fetchall()
    conn.close()

    if not rows:
        return {"note": "no real analytics recorded yet - nothing to learn from until real posts publish and report back"}

    import json
    from collections import defaultdict
    tag_views = defaultdict(list)
    for row in rows:
        try:
            tags = json.loads(row["hashtags"] or "[]")
        except (json.JSONDecodeError, TypeError):
            continue
        for tag in tags:
            tag_views[tag].append(row["views"] or 0)

    real_results = {
        tag: round(sum(views) / len(views), 1)
        for tag, views in tag_views.items() if len(views) >= min_posts
    }
    return dict(sorted(real_results.items(), key=lambda x: x[1], reverse=True))


def get_recommended_posting_time():
    if not os.path.exists(DB_PATH):
        return {"note": "no database yet"}
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM analytics")
    count = cur.fetchone()[0]
    conn.close()
    if count < 10:
        return {"recommendation": None, "note": f"only {count} real analytics records so far - need real published history before a genuine recommendation is possible"}
    return {"recommendation": None, "note": "real time-of-day correlation not yet implemented against real data - build this once posts have actually published"}
