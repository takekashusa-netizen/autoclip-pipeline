#!/usr/bin/env python3
"""
lib/fetch_url.py <job> <url>

Downloads a YouTube (or any yt-dlp-supported site) URL into
projects/<job>/raw/source.mp4 — this is what lets you paste a link instead
of manually downloading first. Works for finished VODs and completed
livestream recordings; a currently-live stream will be downloaded from
whatever has broadcast so far if yt-dlp supports live capture for that URL,
otherwise yt-dlp will wait/retry per its own live-from-start behavior.
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from url_index import record_resolved, record_error
COOKIE_BROWSER = os.environ.get("PIPELINE_COOKIE_BROWSER", "chrome")


def main():
    job, url = sys.argv[1], sys.argv[2]
    try:
        import yt_dlp
    except ImportError:
        print(json.dumps({
            "error": "yt-dlp not installed — run: pip install yt-dlp"
        }))
        sys.exit(1)

    raw_dir = os.path.join(ROOT, "projects", job, "raw")
    os.makedirs(raw_dir, exist_ok=True)
    out_template = os.path.join(raw_dir, "source.%(ext)s")

    # Real gap fixed: the URL used to only get saved AFTER a successful
    # download (see below) — confirmed directly on a real interrupted
    # download, where the .part files survived but the URL that could
    # have resumed it was nowhere to be found, permanently orphaning
    # 233MB of real progress. Writing it here, before the download even
    # starts, means it survives any interruption — a crash, a kill, a
    # network drop — not just a clean success.
    with open(os.path.join(raw_dir, "source_url.json"), "w") as f:
        json.dump({"source_url": url}, f, indent=2)

    ydl_opts = {
        "outtmpl": out_template,
        "format": "bv*[height<=1080]+140/bv*[height<=1080]+ba/b[height<=1080]/b",
        "merge_output_format": "mp4",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "cookiesfrombrowser": (COOKIE_BROWSER,),  # needed — YouTube's bot-check
                                             # otherwise serves broken/empty
                                             # audio streams instead of erroring
        "remote_components": ["ejs:github"],  # top-level option, not per-extractor
        # completed livestream VODs download fine as-is; a still-live stream
        # gets captured from the current point forward unless the extractor
        # supports --live-from-start (site-dependent, not forced here)
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(url, download=True)
        except yt_dlp.utils.DownloadError as e:
            msg = str(e)
            if "Unsupported URL" in msg:
                print(json.dumps({
                    "error": "unsupported site/URL — yt-dlp doesn't recognize this link"
                }))
            elif "Sign in" in msg or "login" in msg.lower() or "cookies" in msg.lower():
                print(json.dumps({
                    "error": "this content requires login/cookies (private, age-restricted, or "
                              "subscriber-only) — not supported without authentication"
                }))
            elif "Private video" in msg or "unavailable" in msg.lower():
                print(json.dumps({"error": "video is private or unavailable"}))
            else:
                print(json.dumps({"error": msg[:500]}))
            # Real fix: record the failure in the shared URL index too,
            # not just print it — otherwise a URL that failed here stays
            # stuck at status "fetching" forever, permanently blocking a
            # legitimate retry of the same link.
            record_error(url, job, msg)
            sys.exit(1)
        downloaded = ydl.prepare_filename(info)
        if info.get("requested_downloads"):
            downloaded = info["requested_downloads"][0].get("filepath", downloaded)

    # normalize to source.mp4 regardless of what extension yt-dlp landed on
    final_path = os.path.join(raw_dir, "source.mp4")
    if os.path.abspath(downloaded) != os.path.abspath(final_path):
        os.replace(downloaded, final_path)

    print(json.dumps({
        "path": final_path,
        "title": info.get("title", ""),
        "duration_sec": info.get("duration"),
        "was_live": bool(info.get("is_live") or info.get("was_live")),
    }))

    # Real gap fixed: the source URL was never saved anywhere, so once a
    # job's raw source got cleaned up (or corrupted), it was permanently
    # unrecoverable even though re-downloading the same URL would have
    # fixed it in minutes. Recorded in TWO places since call order
    # varies: fetch_url.py usually runs BEFORE the pipeline's own
    # state_init (job.json commonly doesn't exist yet at this point,
    # confirmed by testing — a job.json-only fix would silently do
    # nothing in the normal case). A dedicated marker file next to the
    # download always exists regardless of ordering; job.json also gets
    # it when/if it already exists, for convenience when reading job
    # state directly.
    url_info = {"source_url": url, "source_title": info.get("title", "")}
    with open(os.path.join(raw_dir, "source_url.json"), "w") as f:
        json.dump(url_info, f, indent=2)

    # Real fix: fills in the real, resolved metadata (title, duration,
    # the extractor's own canonical id) in the shared cross-job index,
    # not just this job's own source_url.json — this is what lets a
    # future submit of a differently-shaped URL to the SAME content
    # (e.g. a query param added) still be recognized once resolved, and
    # gives a single durable record of every real download this pipeline
    # has ever done, independent of any one job's own files surviving.
    record_resolved(
        url, job,
        title=info.get("title", ""),
        duration_sec=info.get("duration"),
        canonical_id=info.get("id"),
        extractor=info.get("extractor_key") or info.get("extractor"),
        status="done",
    )

    job_json_path = os.path.join(ROOT, "projects", job, "job.json")
    if os.path.exists(job_json_path):
        try:
            with open(job_json_path) as f:
                job_data = json.load(f)
            job_data.update(url_info)
            with open(job_json_path, "w") as f:
                json.dump(job_data, f, indent=2)
        except Exception:
            pass  # best-effort — never let this fail the actual download


if __name__ == "__main__":
    main()
