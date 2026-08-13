#!/usr/bin/env python3
"""
webhook_trigger.py [--port 8765]

A minimal, dependency-free (stdlib only) HTTP webhook listener — the
real "Trigger" step from an n8n/Make-style automation pipeline, just
pointed at this local pipeline instead of a hosted API. Any tool that
can send a POST request (n8n's HTTP node, Make's webhook module, a
plain curl call, a YouTube RSS-to-webhook service, etc.) can kick off
a real clip job without you touching a terminal.

Endpoints:
  GET  /health                    -> {"status": "ok"}
  POST /trigger                   -> launches go.sh, returns immediately
       body: {"url": "...", "job": "optional", "platform": "tiktok|youtube",
              "clip_count": optional int, "content_type": "optional"}

This deliberately does NOT wait for the job to finish — it launches
go.sh detached (matching safe_run.sh's own pattern: nohup, survives
this server restarting or the terminal closing) and returns
immediately with a job id, the same async "poll for status separately"
shape as a real hosted API's task-id-then-poll pattern. Check status
the same way as any other job:
  python3 summarize_clips.py <job>
"""
import argparse
import json
import os
import re
import subprocess
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

ROOT = os.path.dirname(os.path.abspath(__file__))


def sanitize_job_name(name):
    """A job name lands directly in shell commands and filesystem paths
    downstream — this is the one thing that MUST be validated before
    ever reaching a subprocess call, regardless of how trusted the
    caller seems. Only allow safe characters."""
    cleaned = re.sub(r"[^a-zA-Z0-9_-]", "", name)
    return cleaned[:64] if cleaned else None


class Handler(BaseHTTPRequestHandler):
    def _send_json(self, status_code, payload):
        body = json.dumps(payload).encode()
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self._send_json(200, {"status": "ok"})
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/trigger":
            self._send_json(404, {"error": "not found"})
            return

        try:
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length)
            data = json.loads(raw)
        except Exception as e:
            self._send_json(400, {"error": f"invalid JSON body: {e}"})
            return

        url = data.get("url")
        if not url or not isinstance(url, str):
            self._send_json(400, {"error": "missing required field: url"})
            return

        job = data.get("job")
        if job:
            job = sanitize_job_name(job)
            if not job:
                self._send_json(400, {"error": "job name contains no valid characters"})
                return
        else:
            job = f"webhook{int(time.time())}"

        platform = data.get("platform", "youtube")
        if platform not in ("youtube", "tiktok"):
            self._send_json(400, {"error": "platform must be 'youtube' or 'tiktok'"})
            return

        clip_count = data.get("clip_count", 10)
        content_type = data.get("content_type", "gaming")

        cmd = [
            os.path.join(ROOT, "go.sh"), url, job,
            "--platform", platform,
            "--clip-count", str(clip_count),
            "--content-type", content_type,
        ]
        log_path = os.path.join(ROOT, "logs", "webhook", f"{job}.log")
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, "w") as f:
            subprocess.Popen(cmd, stdout=f, stderr=subprocess.STDOUT, cwd=ROOT,
                              start_new_session=True)  # detached — survives this server restarting

        self._send_json(202, {"status": "launched", "job": job, "log": log_path})

    def log_message(self, format, *args):
        print(f"webhook_trigger: {self.address_string()} - {format % args}", flush=True)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=8765)
    args = p.parse_args()

    server = HTTPServer(("0.0.0.0", args.port), Handler)
    print(f"webhook_trigger: listening on port {args.port} — POST /trigger, GET /health", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
