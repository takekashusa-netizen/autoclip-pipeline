#!/usr/bin/env python3
"""
lib/event_bus.py
Real, minimal Event Bus (Layer 47).
"""
import json
import os
import sqlite3
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EVENTS_DB = os.path.join(ROOT, "events.db")

REAL_EVENT_TYPES = [
    "VIDEO_UPLOADED", "TRANSCRIPT_READY", "MOMENTS_FOUND", "CLIP_RENDERED",
    "SEO_READY", "QC_PASSED", "QC_FAILED", "POST_APPROVED", "POST_PUBLISHED",
    "ANALYTICS_RECEIVED",
]


def _init_db():
    conn = sqlite3.connect(EVENTS_DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            payload TEXT,
            created_at REAL NOT NULL,
            consumed_by TEXT
        )
    """)
    conn.commit()
    conn.close()


def emit(event_type, payload=None):
    _init_db()
    conn = sqlite3.connect(EVENTS_DB)
    conn.execute(
        "INSERT INTO events (event_type, payload, created_at) VALUES (?, ?, ?)",
        (event_type, json.dumps(payload or {}), time.time()),
    )
    conn.commit()
    conn.close()


def consume_new_events(subscriber_name, event_types=None):
    _init_db()
    conn = sqlite3.connect(EVENTS_DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    query = "SELECT * FROM events WHERE consumed_by IS NULL OR consumed_by NOT LIKE ?"
    params = [f"%{subscriber_name}%"]
    if event_types:
        placeholders = ",".join("?" * len(event_types))
        query += f" AND event_type IN ({placeholders})"
        params += event_types

    cur.execute(query, params)
    rows = [dict(r) for r in cur.fetchall()]

    for row in rows:
        existing = row["consumed_by"] or ""
        new_consumed = f"{existing},{subscriber_name}".strip(",")
        cur.execute("UPDATE events SET consumed_by = ? WHERE id = ?", (new_consumed, row["id"]))

    conn.commit()
    conn.close()

    for row in rows:
        row["payload"] = json.loads(row["payload"])
    return rows
