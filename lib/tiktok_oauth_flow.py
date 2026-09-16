#!/usr/bin/env python3
"""
lib/tiktok_oauth_flow.py

Real, permanent fix: TikTok's redirect URI registration genuinely
requires https:// (no localhost/http exception, confirmed directly in
the developer portal form validation) - a local HTTP callback server
cannot be registered at all. This version uses a real, already-owned
HTTPS URL (https://takekash.com/oauth-callback) as the redirect and
has you manually copy the ?code= value from the browser's address bar
after TikTok redirects there (the page itself may show a 404 - that is
fine, the real authorization code is in the URL itself regardless of
whether the destination page exists).

Setup, one time, before running this:
1. In your TikTok app's Login Kit product, add this exact Redirect URI:
     https://takekash.com/oauth-callback
2. export TIKTOK_CLIENT_KEY="..." and TIKTOK_CLIENT_SECRET="..."

Usage:
    python3 lib/tiktok_oauth_flow.py
"""
import base64
import hashlib
import json
import os
import secrets
import time
import urllib.parse

import requests

REDIRECT_URI = "https://takekash.com/oauth-callback"
TOKEN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tiktok_token.json")
SCOPES = "user.info.basic,video.publish,video.upload"


def _generate_pkce_pair():
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).decode().rstrip("=")
    return verifier, challenge


def run_oauth_flow():
    client_key = os.environ.get("TIKTOK_CLIENT_KEY")
    client_secret = os.environ.get("TIKTOK_CLIENT_SECRET")
    if not client_key or not client_secret:
        raise RuntimeError("TIKTOK_CLIENT_KEY / TIKTOK_CLIENT_SECRET not set in environment")

    verifier, challenge = _generate_pkce_pair()
    state = secrets.token_urlsafe(16)

    authorize_url = (
        "https://www.tiktok.com/v2/auth/authorize/"
        f"?client_key={client_key}"
        f"&scope={SCOPES}"
        f"&response_type=code"
        f"&redirect_uri={urllib.parse.quote(REDIRECT_URI, safe='')}"
        f"&state={state}"
    )
    authorize_url += f"&code_challenge={challenge}&code_challenge_method=S256"

    print("=" * 70)
    print("Real, actual TikTok login/consent URL - open this in a browser:")
    print(authorize_url)
    print("=" * 70)
    print()
    print("After you log in and approve, TikTok will redirect you to a URL")
    print("starting with https://takekash.com/oauth-callback?code=...")
    print("The page itself may show an error (that page does not exist yet)")
    print("- that is fine. Copy the FULL URL from your browser's address bar")
    print("and paste it below.")
    print()
    redirected_url = input("Paste the full redirected URL here: ").strip()

    parsed = urllib.parse.urlparse(redirected_url)
    params = urllib.parse.parse_qs(parsed.query)
    code = params.get("code", [None])[0]
    returned_state = params.get("state", [None])[0]

    if not code:
        raise RuntimeError("No 'code' parameter found in that URL - paste the full redirected URL.")
    if returned_state != state:
        raise RuntimeError("State mismatch - possible CSRF, aborting.")

    print("Got real authorization code, exchanging it for an access token...")
    resp = requests.post(
        "https://open.tiktokapis.com/v2/oauth/token/",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "client_key": client_key,
            "client_secret": client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": REDIRECT_URI,
            "code_verifier": verifier,
        },
        timeout=30,
    )
    resp.raise_for_status()
    token_data = resp.json()
    token_data["expires_at"] = time.time() + token_data.get("expires_in", 86400)

    with open(TOKEN_FILE, "w") as f:
        json.dump(token_data, f, indent=2)

    print(f"Real, live TikTok token saved to {TOKEN_FILE}")
    print("You can now use lib/tiktok_publish.py to post real videos.")


if __name__ == "__main__":
    run_oauth_flow()
