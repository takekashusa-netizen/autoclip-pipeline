#!/usr/bin/env python3
"""
n8n_api.py — TakeKash n8n Integration API
Runs on port 8766 alongside the dashboard.

Endpoints n8n uses:
  GET  /api/n8n/pending          — clips approved and ready to post
  GET  /api/n8n/clip?id=xxx      — serve the actual .mp4 binary
  POST /api/n8n/mark-published   — mark a clip as published after n8n posts it
  POST /api/n8n/mark-failed      — mark a clip as failed with error message
  GET  /api/n8n/schedule         — full schedule overview
  POST /api/n8n/webhook/done     — pipeline calls this when a job finishes

Start:  python3 n8n_api.py
Daemon: launchd via com.takekash.n8n-api.plist
"""
import json
import os
import sys
import time
import sqlite3
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs
from datetime import datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
QUEUE_PATH = os.path.join(ROOT, "publish_schedule.json")
DB_PATH = os.path.join(ROOT, "takekash.db")
OUTPUTS_DIR = os.path.join(ROOT, "outputs")
PORT = 8766
API_KEY = os.environ.get("N8N_API_KEY", "takekash-n8n-2026")  # set in .zshrc for security


def load_queue():
    try:
        with open(QUEUE_PATH) as f:
            return json.load(f)
    except Exception:
        return []


def save_queue(queue):
    with open(QUEUE_PATH, "w") as f:
        json.dump(queue, f, indent=2)


def json_response(handler, data, status=200):
    body = json.dumps(data, indent=2).encode()
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.end_headers()
    handler.wfile.write(body)


def error_response(handler, msg, status=400):
    json_response(handler, {"error": msg}, status)


class N8NHandler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        ts = datetime.now().strftime("%H:%M:%S")
        print(f"[{ts}] n8n_api: {fmt % args}", flush=True)

    def check_auth(self):
        key = self.headers.get("X-API-Key", "")
        if key != API_KEY:
            error_response(self, "unauthorized", 401)
            return False
        return True

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-API-Key")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        path = parsed.path

        if not self.check_auth():
            return

        # GET /api/n8n/pending — approved clips due to post now
        if path == "/api/n8n/pending":
            queue = load_queue()
            now = datetime.now().isoformat()
            pending = []
            for item in queue:
                if item.get("status") not in ("approved", "pending"):
                    continue
                sched = item.get("scheduled_time", "")
                if sched and sched > now:
                    continue  # not due yet
                video_path = item.get("video_path", "")
                if video_path and not os.path.exists(video_path):
                    continue  # file missing
                pending.append({
                    "content_id": item.get("content_id"),
                    "platform": item.get("platform"),
                    "title": item.get("title", ""),
                    "description": item.get("description", ""),
                    "tags": item.get("tags", []),
                    "hashtags": item.get("hashtags", ""),
                    "video_path": video_path,
                    "scheduled_time": sched,
                    "clip_url": f"http://localhost:{PORT}/api/n8n/clip?id={item.get('content_id')}",
                })
            json_response(self, {"count": len(pending), "clips": pending})

        # GET /api/n8n/clip?id=content_id — serve the .mp4 binary
        elif path == "/api/n8n/clip":
            content_id = qs.get("id", [None])[0]
            if not content_id:
                return error_response(self, "missing id param")
            queue = load_queue()
            item = next((i for i in queue if i.get("content_id") == content_id), None)
            if not item:
                return error_response(self, "content_id not found", 404)
            video_path = item.get("video_path", "")
            if not video_path or not os.path.exists(video_path):
                return error_response(self, "video file not found", 404)
            size = os.path.getsize(video_path)
            self.send_response(200)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Content-Length", str(size))
            self.send_header("Content-Disposition", f'attachment; filename="{os.path.basename(video_path)}"')
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            with open(video_path, "rb") as f:
                while chunk := f.read(65536):
                    self.wfile.write(chunk)

        # GET /api/n8n/schedule — full schedule
        elif path == "/api/n8n/schedule":
            queue = load_queue()
            from collections import Counter
            by_status = dict(Counter(i.get("status") for i in queue))
            by_platform = dict(Counter(i.get("platform") for i in queue))
            json_response(self, {
                "total": len(queue),
                "by_status": by_status,
                "by_platform": by_platform,
                "queue": queue,
            })

        else:
            error_response(self, "not found", 404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if not self.check_auth():
            return

        body = b""
        length = int(self.headers.get("Content-Length", 0))
        if length:
            body = self.rfile.read(length)
        try:
            data = json.loads(body) if body else {}
        except Exception:
            return error_response(self, "invalid JSON")

        # POST /api/n8n/mark-published
        if path == "/api/n8n/mark-published":
            content_id = data.get("content_id")
            platform = data.get("platform")
            post_id = data.get("post_id", "")
            if not content_id:
                return error_response(self, "missing content_id")

            queue = load_queue()
            updated = False
            for item in queue:
                if item.get("content_id") == content_id:
                    if platform and item.get("platform") != platform:
                        continue
                    item["status"] = "published"
                    item["published_at"] = datetime.now().isoformat()
                    item["post_id"] = post_id
                    updated = True
                    break

            if not updated:
                return error_response(self, "content_id not found", 404)

            save_queue(queue)

            # also update SQLite
            try:
                conn = sqlite3.connect(DB_PATH)
                conn.execute(
                    "UPDATE social_posts SET status='published', published_at=? WHERE content_id=?",
                    (datetime.now().isoformat(), content_id)
                )
                conn.commit()
                conn.close()
            except Exception as e:
                print(f"  sqlite update failed (non-fatal): {e}")

            json_response(self, {"ok": True, "content_id": content_id, "status": "published"})

        # POST /api/n8n/mark-failed
        elif path == "/api/n8n/mark-failed":
            content_id = data.get("content_id")
            error_msg = data.get("error", "unknown error")
            if not content_id:
                return error_response(self, "missing content_id")

            queue = load_queue()
            for item in queue:
                if item.get("content_id") == content_id:
                    item["status"] = "failed"
                    item["error_message"] = error_msg
                    item["failed_at"] = datetime.now().isoformat()
                    break

            save_queue(queue)
            json_response(self, {"ok": True, "content_id": content_id, "status": "failed"})

        # POST /api/n8n/webhook/done — pipeline notifies n8n a job finished
        elif path == "/api/n8n/webhook/done":
            job = data.get("job", "unknown")
            clip_count = data.get("clips", 0)
            print(f"  webhook: job={job} clips={clip_count} — n8n can now fetch pending clips")
            json_response(self, {"ok": True, "job": job, "clips": clip_count})

        else:
            error_response(self, "not found", 404)


if __name__ == "__main__":
    os.chdir(ROOT)
    print(f"TakeKash n8n API starting on port {PORT}")
    print(f"API key: {API_KEY[:8]}...")
    print(f"Queue: {QUEUE_PATH}")
    print(f"Endpoints:")
    print(f"  GET  http://localhost:{PORT}/api/n8n/pending")
    print(f"  GET  http://localhost:{PORT}/api/n8n/clip?id=CONTENT_ID")
    print(f"  GET  http://localhost:{PORT}/api/n8n/schedule")
    print(f"  POST http://localhost:{PORT}/api/n8n/mark-published")
    print(f"  POST http://localhost:{PORT}/api/n8n/mark-failed")
    print(f"  POST http://localhost:{PORT}/api/n8n/webhook/done")
    server = HTTPServer(("0.0.0.0", PORT), N8NHandler)
    server.serve_forever()
