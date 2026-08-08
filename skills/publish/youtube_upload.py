#!/usr/bin/env python3
"""
skills/publish/youtube_upload.py <job> <video_path> [--title T] [--description D]
    [--privacy private|unlisted|public] [--tags a,b,c]

Uploads a finished clip to YouTube. Requires youtube_auth_setup.py to have
been run once already (needs skills/publish/youtube_token.json to exist).
Defaults to privacy=private so nothing goes public by accident — pass
--privacy public explicitly when you're ready for that.
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOKEN_PATH = os.path.join(HERE, "youtube_token.json")
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def get_credentials():
    if not os.path.exists(TOKEN_PATH):
        raise RuntimeError(
            f"not authorized yet — run: python3 {os.path.join(HERE, 'youtube_auth_setup.py')}"
        )
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request

    creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(TOKEN_PATH, "w") as f:
            f.write(creds.to_json())
    return creds


def upload(video_path, title, description, privacy, tags):
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    creds = get_credentials()
    youtube = build("youtube", "v3", credentials=creds)

    body = {
        "snippet": {
            "title": title[:100],
            "description": description[:5000],
            "tags": tags or [],
            "categoryId": "22",  # People & Blogs — reasonable default
        },
        "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False},
    }
    media = MediaFileUpload(video_path, chunksize=-1, resumable=True, mimetype="video/mp4")

    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    while response is None:
        status, response = request.next_chunk()
    return response


def main():
    p = argparse.ArgumentParser()
    p.add_argument("job")
    p.add_argument("video_path")
    p.add_argument("--title", default=None)
    p.add_argument("--description", default="")
    p.add_argument("--privacy", default="private", choices=["private", "unlisted", "public"])
    p.add_argument("--tags", default="")
    args = p.parse_args()

    if not os.path.exists(args.video_path):
        print(json.dumps({"error": f"file not found: {args.video_path}"}))
        sys.exit(1)

    try:
        import google.oauth2  # noqa: F401
        import googleapiclient  # noqa: F401
    except ImportError:
        print(json.dumps({
            "error": "missing deps — run: pip install google-auth-oauthlib google-api-python-client"
        }))
        sys.exit(1)

    title = args.title or args.job
    tags = [t.strip() for t in args.tags.split(",") if t.strip()]

    try:
        result = upload(args.video_path, title, args.description, args.privacy, tags)
    except Exception as e:
        print(json.dumps({"error": str(e)[:1000]}))
        sys.exit(1)

    print(json.dumps({
        "video_id": result["id"],
        "url": f"https://youtube.com/watch?v={result['id']}",
        "privacy": args.privacy,
    }))


if __name__ == "__main__":
    main()
