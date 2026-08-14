#!/usr/bin/env python3
"""
saas_server.py [--port 8080]

The real, multi-user server — signup, login, credit purchase via
Stripe, and job submission with real credit deduction. Separate from
dashboard.py (which stays as your own personal single-user control
panel) since a multi-tenant public-facing server has a genuinely
different threat model: it's reachable by the public internet, so
every input here is treated as untrusted, sessions are required for
anything that touches user data or spends credits, and job submission
enforces the balance check server-side (never trust a client-supplied
"I have enough credits" claim).
"""
import argparse
import json
import os
import re
import socketserver
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "lib"))

import saas_db  # noqa: E402
import saas_auth  # noqa: E402
import saas_billing  # noqa: E402


class ThreadingHTTPServer(socketserver.ThreadingMixIn, HTTPServer):
    """Real requirement for a public-facing server, more so than the
    personal dashboard even — many real users could be signing up,
    logging in, and starting checkout sessions concurrently; a
    single-threaded server would make one slow request block every
    other user, a much bigger real problem here than on a
    single-operator tool."""
    daemon_threads = True


def sanitize_job_name(name):
    cleaned = re.sub(r"[^a-zA-Z0-9_-]", "", name)
    return cleaned[:64] if cleaned else None


def get_session_token(handler):
    """Real, standard cookie-based session extraction."""
    cookie_header = handler.headers.get("Cookie", "")
    for part in cookie_header.split(";"):
        part = part.strip()
        if part.startswith("session="):
            return part[len("session="):]
    return None


def require_auth(handler):
    """Real auth check — returns the user dict if the session is valid,
    or None (and has already sent a 401) if not. Every endpoint that
    touches user data or spends credits calls this FIRST, server-side —
    never trusts a client-supplied user_id."""
    token = get_session_token(handler)
    if not token:
        handler._send_json(401, {"error": "not logged in"})
        return None
    user = saas_db.get_session_user(token)
    if not user:
        handler._send_json(401, {"error": "session expired or invalid — please log in again"})
        return None
    return user


class Handler(BaseHTTPRequestHandler):
    def _send_json(self, status_code, payload, set_cookie=None):
        body = json.dumps(payload).encode()
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        if set_cookie:
            self.send_header("Set-Cookie", set_cookie)
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw)

    def do_GET(self):
        if self.path == "/api/me":
            user = require_auth(self)
            if user:
                self._send_json(200, {"email": user["email"], "credits": user["credits"]})
        elif self.path == "/api/my-jobs":
            user = require_auth(self)
            if user:
                self._send_json(200, saas_db.list_user_jobs(user["id"]))
        elif self.path == "/api/credit-packages":
            self._send_json(200, saas_billing.CREDIT_PACKAGES)
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self):
        if self.path == "/api/signup":
            self._handle_signup()
        elif self.path == "/api/login":
            self._handle_login()
        elif self.path == "/api/billing/checkout":
            self._handle_checkout()
        elif self.path == "/api/billing/webhook":
            self._handle_webhook()
        elif self.path == "/api/submit-job":
            self._handle_submit_job()
        else:
            self._send_json(404, {"error": "not found"})

    def _handle_signup(self):
        try:
            data = self._read_json_body()
        except Exception as e:
            self._send_json(400, {"error": f"invalid JSON: {e}"})
            return
        email = data.get("email", "").strip().lower()
        password = data.get("password", "")
        if not saas_auth.valid_email(email):
            self._send_json(400, {"error": "invalid email"})
            return
        if not saas_auth.valid_password(password):
            self._send_json(400, {"error": "password must be at least 8 characters"})
            return
        password_hash, salt = saas_auth.hash_password(password)
        user_id = saas_db.create_user(email, password_hash, salt, starting_credits=20)  # real, small free-trial grant
        if user_id is None:
            self._send_json(409, {"error": "an account with that email already exists"})
            return
        token = saas_db.create_session(user_id)
        self._send_json(201, {"status": "created", "email": email, "credits": 20},
                         set_cookie=f"session={token}; HttpOnly; Path=/; Max-Age=2592000")

    def _handle_login(self):
        try:
            data = self._read_json_body()
        except Exception as e:
            self._send_json(400, {"error": f"invalid JSON: {e}"})
            return
        email = data.get("email", "").strip().lower()
        password = data.get("password", "")
        user = saas_db.get_user_by_email(email)
        if not user or not saas_auth.verify_password(password, user["password_hash"], user["salt"]):
            self._send_json(401, {"error": "invalid email or password"})  # deliberately generic — don't reveal which part was wrong
            return
        token = saas_db.create_session(user["id"])
        self._send_json(200, {"status": "logged in", "email": user["email"], "credits": user["credits"]},
                         set_cookie=f"session={token}; HttpOnly; Path=/; Max-Age=2592000")

    def _handle_checkout(self):
        user = require_auth(self)
        if not user:
            return
        try:
            data = self._read_json_body()
        except Exception as e:
            self._send_json(400, {"error": f"invalid JSON: {e}"})
            return
        package_key = data.get("package", "starter")
        success_url = data.get("success_url", "https://example.com/success")
        cancel_url = data.get("cancel_url", "https://example.com/cancel")
        try:
            checkout_url = saas_billing.create_checkout_session(package_key, user["id"], success_url, cancel_url)
        except Exception as e:
            self._send_json(500, {"error": str(e)})
            return
        self._send_json(200, {"checkout_url": checkout_url})

    def _handle_webhook(self):
        """Real webhook handler — verifies against the RAW body (must
        read it before any JSON parsing touches it), per Stripe's actual
        signature-verification requirement."""
        length = int(self.headers.get("Content-Length", 0))
        raw_body = self.rfile.read(length) if length else b""
        signature = self.headers.get("Stripe-Signature", "")
        try:
            event = saas_billing.verify_and_parse_webhook(raw_body, signature)
        except Exception as e:
            self._send_json(400, {"error": f"webhook verification failed: {e}"})
            return
        if event["type"] == "checkout.session.completed":
            saas_billing.handle_checkout_completed(event)
        self._send_json(200, {"received": True})  # real requirement: respond quickly, don't do slow work inline

    def _handle_submit_job(self):
        user = require_auth(self)
        if not user:
            return
        try:
            data = self._read_json_body()
        except Exception as e:
            self._send_json(400, {"error": f"invalid JSON: {e}"})
            return
        url = data.get("url")
        if not url:
            self._send_json(400, {"error": "missing url"})
            return
        platform = data.get("platform", "longform")
        cost = saas_billing.CREDIT_COSTS.get(
            "longform_window" if platform == "longform" else "short_clip"
        )
        clip_count = int(data.get("clip_count", 1))
        total_cost = cost * clip_count

        # Real, server-side, atomic balance check — the actual security
        # boundary; never trust a client claim of "I can afford this."
        new_balance = saas_db.adjust_credits(user["id"], -total_cost, f"job:{platform}x{clip_count}")
        if new_balance is None:
            self._send_json(402, {"error": f"insufficient credits — need {total_cost}, have {user['credits']}"})
            return

        job = sanitize_job_name(f"user{user['id'][:8]}_{data.get('job', '')}") or f"user{user['id'][:8]}_job"
        saas_db.create_job_record(user["id"], job, total_cost)

        cmd = [os.path.join(ROOT, "go.sh"), url, job, "--platform", platform, "--clip-count", str(clip_count)]
        log_path = os.path.join(ROOT, "logs", "saas", f"{job}.log")
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, "w") as f:
            subprocess.Popen(cmd, stdout=f, stderr=subprocess.STDOUT, cwd=ROOT, start_new_session=True)

        self._send_json(202, {"status": "launched", "job": job, "credits_charged": total_cost, "remaining_credits": new_balance})

    def log_message(self, format, *args):
        print(f"saas_server: {self.address_string()} - {format % args}", flush=True)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=8080)
    args = p.parse_args()

    saas_db.init_db()
    server = ThreadingHTTPServer(("0.0.0.0", args.port), Handler)
    print(f"saas_server: listening on port {args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
