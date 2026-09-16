#!/usr/bin/env python3
"""
lib/content_plan.py
Real Content Plan Generator (Layer 35).
"""
import os
import sqlite3
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT, "takekash.db")


def generate_content_plan(days=7, posts_per_day=1):
    if not os.path.exists(DB_PATH):
        return {"plan": [], "note": "no database yet"}

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("""
        SELECT c.id, c.clip_path, c.game, c.seo_score
        FROM clips c
        WHERE c.status = 'ready'
        ORDER BY c.seo_score DESC NULLS LAST
        LIMIT ?
    """, (days * posts_per_day,))
    ready_clips = [dict(r) for r in cur.fetchall()]
    conn.close()

    plan = []
    now = datetime.now()
    for day_offset in range(days):
        day_date = now + timedelta(days=day_offset)
        day_clips = ready_clips[day_offset * posts_per_day:(day_offset + 1) * posts_per_day]
        plan.append({
            "date": day_date.strftime("%Y-%m-%d"),
            "day_name": day_date.strftime("%A"),
            "clips": day_clips,
            "has_content": len(day_clips) > 0,
        })

    real_days_covered = sum(1 for d in plan if d["has_content"])
    return {
        "plan": plan,
        "real_days_covered": real_days_covered,
        "real_days_requested": days,
        "note": None if real_days_covered == days else f"only {real_days_covered}/{days} days have real ready content"
    }
