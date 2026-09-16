#!/usr/bin/env python3
"""
lib/content_fatigue.py
Real Content Fatigue Detection (Layer 29).
"""
import os
import sqlite3

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT, "takekash.db")


def check_fatigue(lookback=5):
    if not os.path.exists(DB_PATH):
        return {"fatigue_risk": False, "note": "no database yet"}

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT game FROM clips WHERE game IS NOT NULL ORDER BY id DESC LIMIT ?", (lookback,))
    recent_games = [row[0] for row in cur.fetchall()]

    cur.execute("SELECT DISTINCT game FROM clips WHERE game IS NOT NULL")
    all_games = [row[0] for row in cur.fetchall()]
    conn.close()

    if len(recent_games) < lookback:
        return {"fatigue_risk": False, "recent_games": recent_games, "note": "not enough real history yet"}

    most_common = max(set(recent_games), key=recent_games.count)
    dominance = recent_games.count(most_common) / len(recent_games)

    if dominance >= 0.6:
        under_used = [g for g in all_games if g != most_common and g not in recent_games]
        suggestion = under_used[0] if under_used else None
        return {
            "fatigue_risk": True,
            "dominant_game": most_common,
            "dominance_pct": round(dominance * 100),
            "suggested_next": suggestion,
            "recent_games": recent_games,
        }
    return {"fatigue_risk": False, "recent_games": recent_games}
