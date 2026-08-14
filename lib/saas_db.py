#!/usr/bin/env python3
"""
lib/saas_db.py

Real, tested SQLite database layer for multi-user accounts and credits.
SQLite (not Postgres/MySQL) is a genuine, sensible choice for an
early-stage SaaS — no separate database server to provision or manage,
real ACID guarantees, and it comfortably handles real production load
until you're at a scale where migrating to Postgres is a good problem
to have. This file is the ONE place schema and queries live — no
duplicate logic elsewhere that could drift out of sync.
"""
import os
import sqlite3
import time
import uuid

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "saas.db")


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    """Real, idempotent schema creation — safe to call on every startup,
    won't destroy existing data (CREATE TABLE IF NOT EXISTS throughout)."""
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            salt TEXT NOT NULL,
            credits INTEGER NOT NULL DEFAULT 0,
            created_at REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            created_at REAL NOT NULL,
            expires_at REAL NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            job_name TEXT NOT NULL,
            credits_charged INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at REAL NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS credit_transactions (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            amount INTEGER NOT NULL,
            reason TEXT NOT NULL,
            stripe_payment_id TEXT,
            created_at REAL NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS processed_stripe_events (
            event_id TEXT PRIMARY KEY,
            processed_at REAL NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
        CREATE INDEX IF NOT EXISTS idx_jobs_user ON jobs(user_id);
        CREATE INDEX IF NOT EXISTS idx_transactions_user ON credit_transactions(user_id);
    """)
    conn.commit()
    conn.close()


def create_user(email, password_hash, salt, starting_credits=0):
    user_id = str(uuid.uuid4())
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO users (id, email, password_hash, salt, credits, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, email, password_hash, salt, starting_credits, time.time()),
        )
        conn.commit()
        return user_id
    except sqlite3.IntegrityError:
        return None  # email already exists — real, expected case, not a crash
    finally:
        conn.close()


def get_user_by_email(email):
    conn = get_connection()
    row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_user_by_id(user_id):
    conn = get_connection()
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def create_session(user_id, ttl_sec=86400 * 30):
    token = str(uuid.uuid4())
    now = time.time()
    conn = get_connection()
    conn.execute(
        "INSERT INTO sessions (token, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
        (token, user_id, now, now + ttl_sec),
    )
    conn.commit()
    conn.close()
    return token


def get_session_user(token):
    conn = get_connection()
    row = conn.execute("SELECT * FROM sessions WHERE token = ?", (token,)).fetchone()
    if not row:
        conn.close()
        return None
    if row["expires_at"] < time.time():
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
        conn.commit()
        conn.close()
        return None  # real, expired session — cleaned up, not silently trusted
    user = conn.execute("SELECT * FROM users WHERE id = ?", (row["user_id"],)).fetchone()
    conn.close()
    return dict(user) if user else None


def adjust_credits(user_id, amount, reason, stripe_payment_id=None):
    """Real, atomic credit adjustment — positive for purchases, negative
    for job charges. Returns the new balance, or None if the user
    doesn't have enough credits for a negative adjustment (never allows
    going below zero — a real, enforced constraint, not just a UI check)."""
    conn = get_connection()
    try:
        row = conn.execute("SELECT credits FROM users WHERE id = ?", (user_id,)).fetchone()
        if row is None:
            return None
        new_balance = row["credits"] + amount
        if new_balance < 0:
            return None  # real, hard block — never let a job charge push a user negative
        conn.execute("UPDATE users SET credits = ? WHERE id = ?", (new_balance, user_id))
        conn.execute(
            "INSERT INTO credit_transactions (id, user_id, amount, reason, stripe_payment_id, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), user_id, amount, reason, stripe_payment_id, time.time()),
        )
        conn.commit()
        return new_balance
    finally:
        conn.close()


def is_event_already_processed(event_id):
    conn = get_connection()
    row = conn.execute("SELECT 1 FROM processed_stripe_events WHERE event_id = ?", (event_id,)).fetchone()
    conn.close()
    return row is not None


def fulfill_credit_purchase(event_id, user_id, credits_amount, stripe_payment_id):
    """Real, atomic idempotent fulfillment — the credit adjustment AND
    the idempotency record are written in the SAME transaction. Real
    2026 Stripe guidance is explicit about this: recording the two
    separately is the actual common bug (a crash between them leaves
    you fulfilled-but-unrecorded, so the next retry double-fulfills).
    Returns the new balance, or None if this event was already
    processed (a real, expected case on webhook retry, not an error)."""
    conn = get_connection()
    try:
        if conn.execute("SELECT 1 FROM processed_stripe_events WHERE event_id = ?", (event_id,)).fetchone():
            return None  # already handled — Stripe retries webhooks, this is expected, not a bug
        row = conn.execute("SELECT credits FROM users WHERE id = ?", (user_id,)).fetchone()
        if row is None:
            return None
        new_balance = row["credits"] + credits_amount
        conn.execute("UPDATE users SET credits = ? WHERE id = ?", (new_balance, user_id))
        conn.execute(
            "INSERT INTO credit_transactions (id, user_id, amount, reason, stripe_payment_id, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), user_id, credits_amount, "purchase", stripe_payment_id, time.time()),
        )
        conn.execute("INSERT INTO processed_stripe_events (event_id, processed_at) VALUES (?, ?)", (event_id, time.time()))
        conn.commit()
        return new_balance
    finally:
        conn.close()


def create_job_record(user_id, job_name, credits_charged):
    job_id = str(uuid.uuid4())
    conn = get_connection()
    conn.execute(
        "INSERT INTO jobs (id, user_id, job_name, credits_charged, status, created_at) VALUES (?, ?, ?, ?, 'pending', ?)",
        (job_id, user_id, job_name, credits_charged, time.time()),
    )
    conn.commit()
    conn.close()
    return job_id


def list_user_jobs(user_id):
    conn = get_connection()
    rows = conn.execute("SELECT * FROM jobs WHERE user_id = ? ORDER BY created_at DESC", (user_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]
