#!/usr/bin/env python3
"""
lib/youtube_publish.py <mode> ...

mode = "title" <clip_json_path>
  Generates an SEO title/description from a single clip's real data
  (its transcript text, tags, engagement score) — not a template with
  the video's ID slapped in, an actual title built from what's IN the
  clip. Prints JSON: {"title": ..., "description": ..., "tags": [...]}

mode = "upload" <video_path> <title> <description> <tags_csv>
  Uploads via YouTube Data API v3. Requires OAuth credentials already
  set up (see setup instructions — this is a real, external one-time
  step tied to your own Google account, not something automatable
  without your direct action).

Title generation approach: pulls the actual hook/highlight text from
the clip's transcript (the same text already used for captions/beat
cards — these were SPECIFICALLY chosen for being punchy), plus a
content-type-aware suffix, plus a gunfire/impact flag if that's why
the clip was selected. This is heuristic, built from real clip data —
not a trained SEO model, and not guaranteed to outperform a human
writing titles by hand. Treat it as a solid, fast first draft.
"""
import json
import os
import re
import sys

GAMING_SUFFIXES = ["Insane Gaming Moment", "You Won't Believe This", "Clutch Play", "Gaming Highlights"]
GENERAL_SUFFIXES = ["Highlight Reel", "Best Moment", "You Have To See This"]


def clean_hook_text(text):
    """Trim to a title-appropriate length and strip trailing punctuation
    that looks awkward mid-title."""
    text = text.strip()
    text = re.sub(r"\s+", " ", text)
    if len(text) > 70:
        text = text[:67].rsplit(" ", 1)[0] + "..."
    return text.strip(" .,!?")


def generate_title(clip_data, content_type="general"):
    """clip_data: {"text": "...", "tags": [...] or score-derived hint,
    "engagement_score": int, "has_impact": bool}"""
    hook = clean_hook_text(clip_data.get("text", "")) or clip_data.get("preview", "")
    has_impact = clip_data.get("has_impact") or "gunfire" in (clip_data.get("text") or "").lower()

    if hook:
        if has_impact:
            title = f"{hook} 🔥 INSANE Gaming Moment"
        else:
            title = f"{hook} | {GAMING_SUFFIXES[0] if content_type == 'gaming' else GENERAL_SUFFIXES[0]}"
    else:
        title = GAMING_SUFFIXES[0] if content_type == "gaming" else GENERAL_SUFFIXES[0]

    if len(title) > 100:  # YouTube's real hard limit
        title = title[:97] + "..."
    return title


def generate_description(clip_data, source_title=None, source_url=None):
    lines = []
    hook = clean_hook_text(clip_data.get("text", ""))
    if hook:
        lines.append(hook)
        lines.append("")
    if source_title:
        lines.append(f"From: {source_title}")
    if source_url:
        lines.append(source_url)
    lines.append("")
    score = clip_data.get("engagement_score")
    tags_line = "#gaming #highlights #clips"
    if clip_data.get("has_impact"):
        tags_line += " #action #intense"
    lines.append(tags_line)
    return "\n".join(lines).strip()


def generate_tags(clip_data, content_type="general"):
    tags = ["highlights", "clips", "shorts"]
    if content_type == "gaming":
        tags += ["gaming", "gameplay", "gaming highlights"]
    if clip_data.get("has_impact"):
        tags += ["action", "intense moments"]
    return tags


def main():
    mode = sys.argv[1]

    if mode == "title":
        clip_json_path = sys.argv[2]
        content_type = sys.argv[3] if len(sys.argv) > 3 else "general"
        with open(clip_json_path) as f:
            clip_data = json.load(f)
        result = {
            "title": generate_title(clip_data, content_type),
            "description": generate_description(clip_data),
            "tags": generate_tags(clip_data, content_type),
        }
        print(json.dumps(result, indent=2))
        return

    if mode == "upload":
        video_path, title, description, tags_csv = sys.argv[2:6]
        upload_video(video_path, title, description, tags_csv.split(","))
        return

    print(f"unknown mode: {mode}", file=sys.stderr)
    sys.exit(1)


def upload_video(video_path, title, description, tags):
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload
        import pickle
    except ImportError:
        print(json.dumps({
            "error": "YouTube upload libraries not installed. Run: "
                     "pip install google-auth-oauthlib google-api-python-client --break-system-packages"
        }))
        sys.exit(1)

    SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
    TOKEN_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "youtube_token.pickle")
    CLIENT_SECRETS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "youtube_client_secret.json")

    creds = None
    if os.path.exists(TOKEN_PATH):
        with open(TOKEN_PATH, "rb") as f:
            creds = pickle.load(f)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(CLIENT_SECRETS_PATH):
                print(json.dumps({
                    "error": f"No OAuth client secrets found at {CLIENT_SECRETS_PATH}. "
                             f"See setup instructions to create one in Google Cloud Console."
                }))
                sys.exit(1)
            flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS_PATH, SCOPES)
            creds = flow.run_local_server(port=0)  # opens a real browser window for one-time consent
        with open(TOKEN_PATH, "wb") as f:
            pickle.dump(creds, f)

    youtube = build("youtube", "v3", credentials=creds)
    body = {
        "snippet": {"title": title, "description": description, "tags": tags, "categoryId": "20"},  # 20 = Gaming
        "status": {"privacyStatus": "private"},  # real safety default — never auto-publish public without review
    }
    media = MediaFileUpload(video_path, chunksize=-1, resumable=True)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    while response is None:
        status, response = request.next_chunk()
    print(json.dumps({"video_id": response.get("id"), "url": f"https://youtu.be/{response.get('id')}"}))


if __name__ == "__main__":
    main()
