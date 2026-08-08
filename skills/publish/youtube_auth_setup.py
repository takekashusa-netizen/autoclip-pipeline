#!/usr/bin/env python3
"""
skills/publish/youtube_auth_setup.py

Run this ONCE, locally, on the machine that will do the uploading:

    python3 skills/publish/youtube_auth_setup.py

It opens a browser for you to sign into the YouTube account you want to
publish to, then saves a reusable token to skills/publish/youtube_token.json.
After that, uploads happen with no further browser interaction — the token
auto-refreshes.

Prerequisites (one-time, in Google Cloud Console):
  1. Create a project at https://console.cloud.google.com
  2. Enable "YouTube Data API v3" for it
  3. Create an OAuth 2.0 Client ID, type "Desktop app"
  4. Download the JSON, save it as skills/publish/client_secret.json

Requires: pip install google-auth-oauthlib google-api-python-client
"""
import os
import sys

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
HERE = os.path.dirname(os.path.abspath(__file__))
CLIENT_SECRET_PATH = os.path.join(HERE, "client_secret.json")
TOKEN_PATH = os.path.join(HERE, "youtube_token.json")


def main():
    if not os.path.exists(CLIENT_SECRET_PATH):
        print(f"Missing {CLIENT_SECRET_PATH}")
        print("Download your OAuth client JSON from Google Cloud Console")
        print("(APIs & Services > Credentials > OAuth 2.0 Client IDs, type 'Desktop app')")
        print(f"and save it exactly there.")
        sys.exit(1)

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print("Missing dependency. Run:")
        print("  pip install google-auth-oauthlib google-api-python-client")
        sys.exit(1)

    flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_PATH, SCOPES)
    creds = flow.run_local_server(port=0)

    with open(TOKEN_PATH, "w") as f:
        f.write(creds.to_json())

    print(f"Saved token to {TOKEN_PATH}")
    print("YouTube uploads are now authorized for this account.")


if __name__ == "__main__":
    main()
