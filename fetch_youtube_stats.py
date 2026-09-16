#!/usr/bin/env python3
"""
Pulls real per-video stats (views/likes/comments/privacy) for every video on
the channel via the YouTube Data API, using the existing youtube_token.pickle.

Run this ON THE MAC in a real terminal (real network route to Google),
from the autoclip-pipeline root:
    python3 fetch_youtube_stats.py
"""
import pickle
import json
import os

from googleapiclient.discovery import build
from google.auth.transport.requests import Request

ROOT = os.path.dirname(os.path.abspath(__file__))
TOKEN_PATH = os.path.join(ROOT, "youtube_token.pickle")
OUT_PATH = os.path.join(ROOT, "yt_video_stats.json")


def main():
    with open(TOKEN_PATH, "rb") as f:
        creds = pickle.load(f)

    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(TOKEN_PATH, "wb") as f:
            pickle.dump(creds, f)

    yt = build("youtube", "v3", credentials=creds)

    ch = yt.channels().list(part="contentDetails,statistics,snippet", mine=True).execute()
    channel = ch["items"][0]
    uploads_playlist = channel["contentDetails"]["relatedPlaylists"]["uploads"]
    print("Channel:", channel["snippet"]["title"])
    print("Channel stats:", json.dumps(channel["statistics"], indent=2))

    video_ids = []
    next_page = None
    while True:
        resp = yt.playlistItems().list(
            part="contentDetails,snippet",
            playlistId=uploads_playlist,
            maxResults=50,
            pageToken=next_page,
        ).execute()
        for item in resp["items"]:
            video_ids.append(item["contentDetails"]["videoId"])
        next_page = resp.get("nextPageToken")
        if not next_page:
            break

    print(f"Total videos found: {len(video_ids)}")

    all_stats = []
    for i in range(0, len(video_ids), 50):
        batch = video_ids[i:i + 50]
        resp = yt.videos().list(part="statistics,snippet,status", id=",".join(batch)).execute()
        for item in resp["items"]:
            stats = item.get("statistics", {})
            all_stats.append({
                "id": item["id"],
                "title": item["snippet"]["title"],
                "privacy": item["status"]["privacyStatus"],
                "publishedAt": item["snippet"]["publishedAt"],
                "views": int(stats.get("viewCount", 0)),
                "likes": int(stats.get("likeCount", 0)),
                "comments": int(stats.get("commentCount", 0)),
            })

    all_stats.sort(key=lambda v: v["views"], reverse=True)

    with open(OUT_PATH, "w") as f:
        json.dump(all_stats, f, indent=2)

    print(f"Saved {len(all_stats)} video stats to {OUT_PATH}")
    print("\nTop 10 by views:")
    for v in all_stats[:10]:
        print(f"  {v['views']:>7} views | {v['likes']:>5} likes | {v['comments']:>4} comments | {v['title'][:70]}")


if __name__ == "__main__":
    main()
