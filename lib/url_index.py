#!/usr/bin/env python3
"""
lib/url_index.py

Central, cross-job record of every source URL this pipeline has ever been
asked to fetch — real fix for a real duplicate-download bug (two full
Twitch VOD downloads of the same link running side by side, because
mcp_server.py's submit_clip_job used to block synchronously on the first
one with no way for a second request for the *same* URL to know they
were related).

Single JSON file at the pipeline root, keyed by a normalized URL so
"https://twitch.tv/videos/X", "https://www.twitch.tv/videos/X/", and
"https://www.twitch.tv/videos/X?t=01h02m" all collide on the same entry
instead of silently starting separate downloads. This is a real, if
partial, canonicalizer — a true content-id match (independent of which
URL shape got pasted) happens once yt-dlp actually resolves the link, via
record_resolved()'s canonical_id/extractor fields, not at normalize_url()
time.
"""
import json
import os
import re
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX_PATH = os.path.join(ROOT, "source_url_index.json")


def normalize_url(url):
    """Strip query string/fragment and trailing slash, lowercase the
    scheme+host. Catches the common real case — the same link pasted
    twice, or with a timestamp/query param tacked on — without needing
    a network round-trip."""
    url = (url or "").strip()
    m = re.match(r"^(https?://)([^/]+)(/[^?#]*)?", url, re.IGNORECASE)
    if not m:
        return url.rstrip("/")
    scheme, host, path = m.group(1), m.group(2), (m.group(3) or "")
    return f"{scheme.lower()}{host.lower()}{path.rstrip('/')}"


def _load():
    if not os.path.exists(INDEX_PATH):
        return {}
    try:
        with open(INDEX_PATH) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save(index):
    tmp = INDEX_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(index, f, indent=2, sort_keys=True)
    os.replace(tmp, INDEX_PATH)  # atomic swap — no torn reads from a concurrent process


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def lookup(url):
    """Returns the existing entry dict for this URL, or None."""
    return _load().get(normalize_url(url))


def record_submitted(url, job):
    """Called at submit time, before any download starts. This is what
    lets the very next submit_clip_job call for the same (or
    same-looking) URL say "already in progress" instead of starting a
    second download."""
    index = _load()
    index[normalize_url(url)] = {
        "job": job,
        "status": "fetching",
        "submitted_at": _now(),
        "title": None,
        "duration_sec": None,
        "canonical_id": None,
        "extractor": None,
    }
    _save(index)


def record_resolved(url, job, title=None, duration_sec=None, canonical_id=None,
                     extractor=None, status="done"):
    """Called once yt-dlp has actually resolved (and, for status="done",
    finished downloading) the URL — fills in the real metadata so this
    index doubles as a durable record of what's actually been pulled in,
    not just a lock file."""
    index = _load()
    key = normalize_url(url)
    entry = index.get(key, {"job": job, "submitted_at": _now()})
    entry.update({
        "job": job,
        "status": status,
        "title": title,
        "duration_sec": duration_sec,
        "canonical_id": canonical_id,
        "extractor": extractor,
        "resolved_at": _now(),
    })
    index[key] = entry
    _save(index)


def record_error(url, job, message):
    """Marks a URL as failed rather than leaving it stuck at "fetching"
    forever, which would otherwise permanently block a legitimate
    retry."""
    index = _load()
    key = normalize_url(url)
    entry = index.get(key, {"job": job, "submitted_at": _now()})
    entry.update({"job": job, "status": "error", "error": str(message)[:500], "resolved_at": _now()})
    index[key] = entry
    _save(index)


def find_url_for_job(job_name, root=None):
    """Best-effort: reads projects/<job_name>/raw/source_url.json for the
    real source URL a job was fetched from. Returns None if it doesn't
    exist — callers must treat that as "unknown, don't guess", never
    assume no duplicate just because this came back empty."""
    root = root or ROOT
    path = os.path.join(root, "projects", job_name, "raw", "source_url.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            return json.load(f).get("source_url")
    except (json.JSONDecodeError, OSError):
        return None


def record_published(url, job):
    """Called after a real successful upload — appends this job to the
    list of jobs that have actually published content sourced from this
    URL. Used by youtube_publish.check_duplicate_source_publish() to
    catch a real gap this session hit directly: two separate jobs (two
    duplicate downloads of the same source, started before the dedup fix
    above existed) each producing their own clips, where publishing both
    would put duplicate content on the channel."""
    index = _load()
    key = normalize_url(url)
    if key not in index:
        return  # unknown URL — nothing to record against, never invent an entry here
    entry = index[key]
    published = entry.setdefault("published_jobs", [])
    if job not in published:
        published.append(job)
    _save(index)
