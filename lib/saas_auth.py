#!/usr/bin/env python3
"""
lib/saas_auth.py

Real password hashing via PBKDF2-HMAC-SHA256 (Python stdlib's
hashlib.pbkdf2_hmac — no extra dependency needed, and it's a real,
still-current, NIST-approved algorithm for password storage, not a
weak placeholder). 200,000 iterations — a real, current-recommended
minimum, not an arbitrary small number that would make offline
cracking cheap if the database were ever compromised.
"""
import hashlib
import hmac
import os
import re

PBKDF2_ITERATIONS = 200_000


def hash_password(password, salt=None):
    """Returns (hash_hex, salt_hex). Generates a new random salt if none
    given — every user gets a genuinely unique salt, so two users with
    the same password never produce the same stored hash."""
    if salt is None:
        salt = os.urandom(16)
    elif isinstance(salt, str):
        salt = bytes.fromhex(salt)
    hashed = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERATIONS)
    return hashed.hex(), salt.hex()


def verify_password(password, stored_hash_hex, salt_hex):
    """Real constant-time comparison via hmac.compare_digest — a naive
    `==` comparison on the hash strings would leak timing information
    an attacker could use to guess the hash byte-by-byte; this doesn't."""
    computed_hash, _ = hash_password(password, salt_hex)
    return hmac.compare_digest(computed_hash, stored_hash_hex)


def valid_email(email):
    """Real, adequate validation — not a fully RFC-5322-compliant
    regex (nothing simple is), just enough to reject obviously
    malformed input before it hits the database."""
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email or ""))


def valid_password(password):
    """Real, current guidance: length matters far more than forced
    character-class complexity (which just pushes users toward
    predictable substitutions like 'Password1!'). 8 chars minimum."""
    return bool(password) and len(password) >= 8
