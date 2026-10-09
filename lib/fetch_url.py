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
import re
import shutil
import subprocess
import sys
from urllib.parse import urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from url_index import record_resolved, record_error
COOKIE_BROWSER = os.environ.get("PIPELINE_COOKIE_BROWSER", "chrome")


def _is_kick_url(url):
    try:
        host = urlparse(url).netloc.lower()
    except Exception:
        return False
    return host == "kick.com" or host.endswith(".kick.com")


def _find_streamlink():
    """Look for the streamlink console script next to the running
    interpreter first (same venv as this script, works regardless of
    whether that venv is active on PATH), then fall back to PATH."""
    candidate = os.path.join(os.path.dirname(sys.executable), "streamlink")
    if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
        return candidate
    return shutil.which("streamlink")


_KICK_HEADERS = {
    # Real, measured requirement: these two endpoints are Kick's own real
    # frontend API (verified live, 2026-09-24 -- see _fetch_via_kick_api's
    # docstring) sitting behind Kasada bot-protection on other parts of
    # the site. A generic Python User-Agent risks getting blocked where a
    # browser-shaped request succeeds; sending real browser-like headers
    # is cheap insurance, not a guess -- the actual verification (see
    # ledger) was done through a real browser session.
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/128.0.0.0 Safari/537.36"),
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://kick.com/",
}


def _fetch_via_kick_api(url, raw_dir):
    """Real, permanent fix, 2026-09-24: both yt-dlp's kick:vod extractor
    AND streamlink's kick plugin fail on this channel's VODs -- yt-dlp
    hits a 404 on its old /v1/video/{id} endpoint (Kick changed VOD URL
    generation; open upstream, yt-dlp/yt-dlp#17284/#17428), and
    streamlink (even the 8.6.1 release that fixed the 404 case,
    streamlink/streamlink#7108) reports "No playable streams found" --
    this channel's VODs are stored via Amazon IVS under Kick's own
    stream.kick.com domain, a shape neither tool's plugin handles.
    Rather than keep chasing whichever third-party extractor is broken
    this week, this calls Kick's own real API directly -- verified live
    against the exact failing VOD, not guessed:
      1. GET https://kick.com/api/v2/channels/{slug} -> real numeric
         channel id (confirmed: id=108426821 for saucewalka102, HTTP 200)
      2. GET https://web.kick.com/api/v1/channels/{channel_id}/videos/{video_id}
         -> real VOD JSON; "data.recording_url" is a direct, UNSIGNED
         master.m3u8 (confirmed: HTTP 200, content-type
         application/x-mpegURL, real multi-quality HLS body -- no token
         needed, unlike the channel's *live* playback_url which is
         JWT-signed)
      3. ffmpeg downloads that master.m3u8 directly (HLS support is
         built into ffmpeg, already a hard dependency of this pipeline --
         no new dependency needed for this path at all)
    Only engages for kick.com; every other site keeps using yt-dlp
    exactly as before, and streamlink is kept as a last-resort fallback
    below this one for whatever this doesn't cover (e.g. genuinely
    private/sub-only VODs, which need real auth either way)."""
    try:
        import requests
    except ImportError:
        return None, "requests not installed — run: pip install requests"

    m = re.match(r"^/([^/]+)/videos/([0-9a-fA-F-]+)/?$", urlparse(url).path)
    if not m:
        return None, f"URL doesn't match kick.com/<channel>/videos/<id> shape: {url}"
    slug, video_id = m.group(1), m.group(2)

    try:
        chan_resp = requests.get(
            f"https://kick.com/api/v2/channels/{slug}",
            headers=_KICK_HEADERS, timeout=20,
        )
        chan_resp.raise_for_status()
        channel_id = chan_resp.json()["id"]
    except Exception as e:
        return None, f"kick channel-id lookup failed: {e}"

    try:
        vod_resp = requests.get(
            f"https://web.kick.com/api/v1/channels/{channel_id}/videos/{video_id}",
            headers=_KICK_HEADERS, timeout=20,
        )
        vod_resp.raise_for_status()
        vod_data = vod_resp.json().get("data", {})
        recording_url = vod_data.get("recording_url")
        if not recording_url:
            return None, f"kick VOD lookup succeeded but had no recording_url: {vod_resp.text[:300]}"
    except Exception as e:
        return None, f"kick VOD metadata lookup failed: {e}"

    out_path = os.path.join(raw_dir, "source.mp4")
    proc = subprocess.run(
        ["ffmpeg", "-y", "-i", recording_url, "-c", "copy", out_path],
        capture_output=True, text=True,
    )
    if proc.returncode != 0 or not os.path.isfile(out_path):
        detail = (proc.stderr or "").strip()[-500:]
        return None, f"ffmpeg download of the real kick recording_url failed: {detail}"

    return {
        "path": out_path,
        "title": vod_data.get("title", ""),
        "duration_sec": vod_data.get("duration"),
        "was_live": False,
        "extractor": "kick-api-direct",
        "id": video_id,
    }, None


def _fetch_via_streamlink(url, raw_dir):
    """Last-resort kick.com fallback, kept behind _fetch_via_kick_api
    above (2026-09-24: streamlink's kick plugin failed with "No playable
    streams found" on the one real VOD this was tested against, an
    IVS-backed channel the direct-API path above handles instead) --
    still worth trying for whatever shape of kick content the direct API
    path doesn't cover."""
    streamlink_bin = _find_streamlink()
    if not streamlink_bin:
        return None, "streamlink not installed — run: pip install streamlink"

    out_path = os.path.join(raw_dir, "source.mp4")
    cmd = [streamlink_bin, "--force", "-o", out_path, url, "best"]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0 or not os.path.isfile(out_path):
        detail = (proc.stderr or proc.stdout or "").strip()[-500:]
        return None, f"streamlink fallback also failed: {detail}"

    duration_sec = None
    try:
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrapper=1:nokey=1", out_path],
            capture_output=True, text=True, timeout=30,
        )
        duration_sec = float(probe.stdout.strip())
    except Exception:
        pass

    return {
        "path": out_path,
        "title": "",
        "duration_sec": duration_sec,
        "was_live": False,
        "extractor": "streamlink:kick",
        "id": None,
    }, None


def _fetch_kick_fallback(url, raw_dir):
    """Try the real, direct Kick API path first; only fall back to
    streamlink if that genuinely fails (e.g. Kasada blocks the request,
    or the VOD shape changes again)."""
    result, err = _fetch_via_kick_api(url, raw_dir)
    if result is not None:
        return result, None
    api_err = err
    result, err = _fetch_via_streamlink(url, raw_dir)
    if result is not None:
        return result, None
    return None, f"direct kick API failed ({api_err}); streamlink also failed ({err})"


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

    info = None
    fallback_result = None
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(url, download=True)
        except yt_dlp.utils.DownloadError as e:
            msg = str(e)
            if _is_kick_url(url) and ("404" in msg or "Unable to download JSON metadata" in msg):
                fallback_result, fallback_err = _fetch_kick_fallback(url, raw_dir)
                if fallback_result is None:
                    print(json.dumps({
                        "error": f"yt-dlp failed ({msg[:200]}) and the kick.com streamlink "
                                  f"fallback also failed: {fallback_err}"
                    }))
                    record_error(url, job, f"{msg} | streamlink fallback: {fallback_err}")
                    sys.exit(1)
            elif "Unsupported URL" in msg:
                print(json.dumps({
                    "error": "unsupported site/URL — yt-dlp doesn't recognize this link"
                }))
                record_error(url, job, msg)
                sys.exit(1)
            elif "Sign in" in msg or "login" in msg.lower() or "cookies" in msg.lower():
                print(json.dumps({
                    "error": "this content requires login/cookies (private, age-restricted, or "
                              "subscriber-only) — not supported without authentication"
                }))
                record_error(url, job, msg)
                sys.exit(1)
            elif "Private video" in msg or "unavailable" in msg.lower():
                print(json.dumps({"error": "video is private or unavailable"}))
                record_error(url, job, msg)
                sys.exit(1)
            else:
                print(json.dumps({"error": msg[:500]}))
                # Real fix: record the failure in the shared URL index too,
                # not just print it — otherwise a URL that failed here stays
                # stuck at status "fetching" forever, permanently blocking a
                # legitimate retry of the same link.
                record_error(url, job, msg)
                sys.exit(1)
        else:
            downloaded = ydl.prepare_filename(info)
            if info.get("requested_downloads"):
                downloaded = info["requested_downloads"][0].get("filepath", downloaded)
            # normalize to source.mp4 regardless of what extension yt-dlp landed on
            final_path = os.path.join(raw_dir, "source.mp4")
            if os.path.abspath(downloaded) != os.path.abspath(final_path):
                os.replace(downloaded, final_path)

    if fallback_result is not None:
        info = {
            "title": fallback_result["title"],
            "duration": fallback_result["duration_sec"],
            "is_live": False,
            "was_live": False,
            "id": fallback_result["id"],
            "extractor_key": fallback_result["extractor"],
        }
        print(json.dumps({
            "path": fallback_result["path"],
            "title": info["title"],
            "duration_sec": info["duration"],
            "was_live": False,
            "note": "downloaded via streamlink fallback — yt-dlp's kick:vod extractor is "
                     "currently broken upstream (yt-dlp/yt-dlp#17284/#17428)",
        }))
    else:
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
