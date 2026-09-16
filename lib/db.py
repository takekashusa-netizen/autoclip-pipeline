#!/usr/bin/env python3
import json
import os
import sqlite3

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT, "takekash.db")
SCHEMA_PATH = os.path.join(ROOT, "lib", "takekash_schema.sql")


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    with open(SCHEMA_PATH) as f:
        conn.executescript(f.read())
    conn.commit()
    conn.close()


def migrate_from_queue(queue_path=None):
    queue_path = queue_path or os.path.join(ROOT, "publish_schedule.json")
    if not os.path.exists(queue_path):
        print(f"no queue file found at {queue_path} - nothing to migrate")
        return

    with open(queue_path) as f:
        queue = json.load(f)

    conn = get_connection()
    cur = conn.cursor()
    clip_id_by_path = {}
    migrated = 0

    for item in queue:
        video_path = item.get("video_path", "")
        if video_path not in clip_id_by_path:
            seo_score = None
            if isinstance(item.get("seo_score"), dict):
                seo_score = item["seo_score"].get("total")
            cur.execute(
                "INSERT INTO clips (source_video, clip_path, seo_score, status) VALUES (?, ?, ?, ?)",
                (video_path, video_path, seo_score, "ready"),
            )
            clip_id_by_path[video_path] = cur.lastrowid

        cur.execute(
            """INSERT INTO social_posts
               (clip_id, platform, title, description, hashtags, status, scheduled_for)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                clip_id_by_path[video_path],
                item.get("platform", ""),
                item.get("title", ""),
                item.get("description", ""),
                json.dumps(item.get("tags", [])),
                item.get("status", "pending"),
                item.get("scheduled_time", ""),
            ),
        )
        migrated += 1

    conn.commit()
    conn.close()
    print(f"migrated {migrated} queue entries into {len(clip_id_by_path)} clips")


if __name__ == "__main__":
    init_db()
    migrate_from_queue()
    print(f"real database ready at {DB_PATH}")
