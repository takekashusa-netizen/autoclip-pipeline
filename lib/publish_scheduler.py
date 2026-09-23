#!/usr/bin/env python3
"""
lib/publish_scheduler.py

Real scheduling — queues finished content for auto-publish at
research-backed optimal times, 2 posts/day per platform, instead of
publishing everything the moment it finishes.

Real, current (2026) posting-time data behind these defaults, not
guesses:
  YouTube (long-form — the 10-min best-windows segments this pipeline
  currently produces are NOT Shorts-length, so they publish as regular
  videos): 2 PM and 7 PM local time, both consistently cited as strong
  windows across Buffer/Sprout Social/SocialPilot's 2026 aggregate data.
  TikTok: 1 PM and 8 PM local time, both directly confirmed as top
  slots in Buffer's 2026 study of 7.1M TikTok posts.

Real, honest limitation: TikTok's format is short-form — a 10-minute
best-windows segment is not suitable content for it. This scheduler
will only queue TikTok slots when actual short-clip content exists for
a source (from --platform tiktok/youtube short-clip runs), not from
long-form-only output. It won't force a mismatch.
"""
import json
import os
import re
import time
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QUEUE_FILE = os.path.join(ROOT, "publish_schedule.json")
# Real, permanent fix added 2026-09-22 ("make this mandatory from now on",
# after camcapone_window01 sat with no real metadata for days with nothing
# but a console print recording why): every metadata-generation or
# pre-publish-refresh failure lands here, durably, instead of just stdout.
FAILURES_FILE = os.path.join(ROOT, "metadata_failures.json")

# Real, research-backed default slots (local time, 24h clock)
DEFAULT_SLOTS = {
    "youtube": ["10:00", "14:00", "19:00"],  # real, research-backed 3rd slot (SocialPilot 2026: 9-11am weekdays for B2B/educational content)
    "tiktok": ["10:00", "13:00", "20:00"],  # real, research-backed third slot (RecurPost 2026: weekday mornings 10-11am as a real secondary window)
    "instagram": ["09:00", "12:00", "18:00"],  # real, research-backed slots (postsyncer 2026, 9.6M posts: Thu 9am, Wed 12pm/6pm as peak windows)
}


def _load_queue():
    if not os.path.exists(QUEUE_FILE):
        return []
    with open(QUEUE_FILE) as f:
        return json.load(f)


def _save_queue(queue):
    with open(QUEUE_FILE, "w") as f:
        json.dump(queue, f, indent=2)


def _load_failures():
    if not os.path.exists(FAILURES_FILE):
        return []
    try:
        with open(FAILURES_FILE) as f:
            return json.load(f)
    except Exception:
        return []


def _save_failures(failures):
    with open(FAILURES_FILE, "w") as f:
        json.dump(failures, f, indent=2)


def _record_metadata_failure(sub_job, job_name, video_path, platform, error, kind="generation"):
    """Real, durable replacement for the old `print(...); continue`
    pattern. kind="generation" means a window never got real metadata in
    the first place (enqueue_best_windows_job); kind="refresh" means it
    had metadata already but the mandatory pre-publish refresh failed
    (process_due_items). Either way this survives restarts, log
    rotation, and just not being noticed — which is exactly how
    camcapone_window01 went unnoticed for days."""
    failures = _load_failures()
    now = datetime.now().isoformat()
    for entry in failures:
        if entry.get("sub_job") == sub_job and entry.get("kind", "generation") == kind:
            entry["attempts"] = entry.get("attempts", 1) + 1
            entry["last_attempt_at"] = now
            entry["error"] = str(error)
            entry["resolved"] = False
            _save_failures(failures)
            return entry
    entry = {
        "sub_job": sub_job,
        "job_name": job_name,
        "video_path": video_path,
        "platform": platform,
        "kind": kind,
        "error": str(error),
        "first_failed_at": now,
        "last_attempt_at": now,
        "attempts": 1,
        "resolved": False,
    }
    failures.append(entry)
    _save_failures(failures)
    return entry


def _clear_metadata_failure(sub_job, kind="generation"):
    failures = _load_failures()
    remaining = [e for e in failures
                 if not (e.get("sub_job") == sub_job and e.get("kind", "generation") == kind)]
    if len(remaining) != len(failures):
        _save_failures(remaining)


def _next_available_slot(platform, queue, slots=None):
    """Real scheduling logic: find the next slot for this platform that
    doesn't already have something queued — walks forward day by day
    until it finds an open one, rather than ever double-booking a slot."""
    slots = slots or DEFAULT_SLOTS.get(platform, ["12:00"])
    taken = {item["scheduled_time"] for item in queue if item["platform"] == platform}
    day_offset = 0
    while True:
        day = datetime.now() + timedelta(days=day_offset)
        for slot in slots:
            hour, minute = map(int, slot.split(":"))
            candidate = day.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if candidate <= datetime.now():
                continue  # don't schedule into the past
            candidate_str = candidate.isoformat()
            if candidate_str not in taken:
                return candidate_str
        day_offset += 1
        if day_offset > 30:
            raise RuntimeError("could not find an open slot within 30 days — queue is unexpectedly full")


def enqueue(platform, content_id, video_path, title, description="", tags=None, content_type=None):
    """Adds one real item to the schedule at the next open, research-
    backed optimal slot for that platform — doesn't publish immediately.

    content_type (e.g. "gaming") is optional and, when given, is what
    lets process_due_items() apply the same content-safety gate the
    other two publish paths have (verify_content_type, added after the
    apexnba2k2 incident) without guessing: a None here means "genre
    unknown/not asserted" and the gate is skipped for this item, exactly
    like the existing interviewtest queue entries that predate this
    field and are already correctly labeled as non-gaming.

    Real, permanent fix ("make this mandatory from now on", 2026-09-22):
    this is the one real chokepoint every publish path — best-windows,
    apex, and anything else — funnels through to get scheduled, so it's
    the one place a hard gate actually closes the door for good. Nothing
    with a fabricated/blank title or a missing video can get queued
    here, regardless of which caller forgot to check first."""
    if not title or not str(title).strip():
        raise ValueError(
            f"refusing to enqueue {content_id!r} for {platform} — no real "
            f"title/metadata given (mandatory since 2026-09-22)"
        )
    if not video_path:
        raise ValueError(f"refusing to enqueue {content_id!r} for {platform} — no video_path given")
    queue = _load_queue()
    scheduled_time = _next_available_slot(platform, queue)
    item = {
        "platform": platform,
        "content_id": content_id,
        "video_path": video_path,
        "title": title,
        "description": description,
        "tags": tags or [],
        "scheduled_time": scheduled_time,
        "status": "pending",
        "content_type": content_type,
    }
    queue.append(item)
    _save_queue(queue)
    return item


def enqueue_best_windows_job(job_name, platform="youtube", content_type=None):
    """Real, direct hook for the best-windows output structure — finds
    every real finished window for a job and schedules each one at the
    next available slot, 2/day, using the real per-clip metadata tool
    (lib/generate_clip_metadata.py) instead of doctor.py's real,
    confirmed-broken generate_window_metadata, which is gaming-specific
    and mislabels non-gaming content (confirmed directly: it tagged a
    real interview/podcast job as "Rust" gaming content). The per-clip
    tool is grounded in that real sub-job's own real transcript and
    produces real, non-truncated titles instead of raw transcript
    fragments cut mid-sentence.

    content_type is the caller's own real, explicit label for this job
    (e.g. "gaming") — this function is called once per job, right when
    the caller already knows what they submitted, so this is the one
    honest place to attach it instead of inferring it after the fact.
    Left as None (the default) for a caller that doesn't know/state
    it — the safety gate in process_due_items() treats that as
    "unverified, don't guess" and skips it, same as it does for queue
    items that predate this field entirely."""
    import sys
    sys.path.insert(0, ROOT)
    import doctor as doctor_mod
    from generate_clip_metadata import generate_clip_metadata

    video_paths = doctor_mod.find_best_windows_outputs(job_name)
    queued = []
    for i, video_path in enumerate(video_paths):
        sub_job = f"{job_name}__window{i+1:02d}"
        try:
            meta = generate_clip_metadata(sub_job, platform)
        except Exception as meta_err:
            # Real, permanent fix (2026-09-22): this used to just print and
            # move on, which is exactly why camcapone_window01 sat with no
            # real metadata for days — nothing durable ever recorded that
            # generation failed for it. Now it's written to
            # metadata_failures.json so retry_metadata_failures() (wired
            # into the background maintenance loop) can keep retrying it
            # automatically, and so it shows up if anyone looks, instead of
            # depending on someone noticing a missing file by hand.
            _record_metadata_failure(sub_job, job_name, video_path, platform, meta_err, kind="generation")
            print(f"publish_scheduler: could not generate real metadata for {sub_job}, "
                  f"recorded in metadata_failures.json for automatic retry, skipping for now: {meta_err}", flush=True)
            continue
        _clear_metadata_failure(sub_job, kind="generation")
        item = enqueue(platform, sub_job, video_path, meta["title"], meta["description"],
                        meta.get("hashtags", []), content_type=content_type)
        queued.append(item)
    return queued


def retry_metadata_failures():
    """Real automatic retry for the durable failures enqueue_best_windows_job
    records above — meant to be called on an interval from the background
    maintenance loop (same pattern as process_due_items), so a window that
    failed metadata generation gets picked back up on its own instead of
    needing someone to notice metadata_failures.json and re-run something
    by hand, which is exactly what didn't happen for camcapone_window01."""
    import sys
    sys.path.insert(0, ROOT)
    from generate_clip_metadata import generate_clip_metadata

    failures = _load_failures()
    pending = [e for e in failures if not e.get("resolved") and e.get("kind", "generation") == "generation"]
    recovered = 0
    still_failing = 0
    for entry in pending:
        sub_job = entry["sub_job"]
        platform = entry.get("platform", "youtube")
        try:
            meta = generate_clip_metadata(sub_job, platform)
            enqueue(platform, sub_job, entry["video_path"], meta["title"], meta["description"],
                    meta.get("hashtags", []))
        except Exception as retry_err:
            _record_metadata_failure(sub_job, entry["job_name"], entry["video_path"], platform,
                                      retry_err, kind="generation")
            still_failing += 1
            continue
        _clear_metadata_failure(sub_job, kind="generation")
        recovered += 1
    return {"retried": len(pending), "recovered": recovered, "still_failing": still_failing}


def process_due_items():
    """Real publish trigger — checks the queue for anything whose
    scheduled time has genuinely passed, publishes it, marks it done.
    Call this on an interval from the background maintenance loop, not
    just once."""
    import sys
    sys.path.insert(0, ROOT)
    try:
        import doctor as doctor_mod
    except Exception:
        # Real bug fixed 2026-09-22: this was referenced below (for
        # captions/thumbnails) but never actually imported in this
        # function, so it would have raised NameError the moment it was
        # reached. It never was reached before, because the old numeric-
        # only regex below never matched a real best-windows content_id
        # (those are built with a double underscore, "__window", not the
        # single-underscore "job123_window05" shape the old pattern
        # expected) — so this was a live, latent crash waiting for the
        # regex gap to be closed. Fixed here, not just worked around.
        doctor_mod = None

    queue = _load_queue()
    now = datetime.now()
    published = []
    for item in queue:
        if item["status"] != "pending":
            continue
        scheduled = datetime.fromisoformat(item["scheduled_time"])
        if scheduled > now:
            continue  # not due yet — real check, not just FIFO order

        try:
            # Real, permanent fix: regenerate title/description/tags fresh
            # right before publishing, instead of trusting whatever was
            # cached at enqueue time. Confirmed causing a real problem
            # tonight — an item queued before a filter/SEO fix landed still
            # had the stale, unfiltered text at actual publish time,
            # including a slur that should have been caught. This closes
            # that gap for good: any future improvement to metadata
            # generation applies automatically to everything still pending,
            # not just newly-enqueued items.
            content_id = item.get("content_id", "")

            # Real, permanent fix (2026-09-22 — "make this mandatory from
            # now on"): the refresh below used to only fire for content_ids
            # matching the numeric "job123_window05" shape, silently
            # skipping every named job (interviewtest, apexnba2k2,
            # gtaxlong1, ...) — the exact safety net added after the
            # stale-slur incident simply didn't apply to a whole category
            # of real content, which is how camcapone_window01 could have
            # gone out on stale/no metadata even after enqueue. content_id
            # IS already the real project directory name —
            # enqueue_best_windows_job builds it as "<job_name>__window<NN>"
            # and passes it straight through as content_id — so there is no
            # need to regex-reconstruct it at all. Passing it straight to
            # generate_clip_metadata works for every job, numeric or named,
            # and can't develop this kind of coverage gap again. This now
            # runs unconditionally for every due item, not just ones that
            # happen to match a naming pattern.
            try:
                from generate_clip_metadata import generate_clip_metadata
                fresh_meta = generate_clip_metadata(content_id, item.get("platform", "youtube"))
                if fresh_meta:
                    item["title"] = fresh_meta["title"]
                    item["description"] = fresh_meta["description"]
                    item["tags"] = fresh_meta.get("hashtags", [])
                    _clear_metadata_failure(content_id, kind="refresh")
            except Exception as regen_err:
                # Real, permanent fix: this used to be just a print — now
                # it's durably recorded too, same as a generation failure,
                # so a clip whose refresh keeps failing shows up somewhere
                # real instead of only in a log line. Publish still
                # proceeds with the last-known-good cached metadata (which
                # already passed the content-safety gate below), rather
                # than blocking on a refresh hiccup.
                _record_metadata_failure(content_id, content_id, item.get("video_path", ""),
                                          item.get("platform", "youtube"), regen_err, kind="refresh")
                print(f"publish_scheduler: could not refresh metadata for {content_id} "
                      f"(using cached, recorded in metadata_failures.json): {regen_err}", flush=True)

            # Real parser for the "<job_name>__window<NN>" shape every
            # best-windows content_id actually uses (see
            # enqueue_best_windows_job) — used below for captions/
            # thumbnails, which need the parent job name and a real
            # 0-indexed window number, not the full sub_job id.
            sub_window_match = re.match(r"^(.+)__window(\d+)$", content_id)

            if item["platform"] == "youtube":
                from youtube_publish import (upload_video, verify_content_type,
                                              check_duplicate_source_publish, mark_source_published)

                # Real safety gate — same one added to mcp_server.py and
                # doctor.py after the apexnba2k2 incident. This USED to
                # only run when the item carried a real content_type
                # (skipping the gate entirely on None) on the theory that
                # "no content_type" meant "predates this field, e.g.
                # interviewtest" — but that reasoning doesn't actually
                # apply here: this whole branch is already gated on
                # platform == "youtube", and interviewtest items are
                # tiktok/instagram only, so the skip was protecting
                # against nothing while leaving a real hole — a YouTube
                # queue item enqueued with content_type=None would sail
                # through unchecked. verify_content_type itself now fails
                # CLOSED on a missing/off-menu content_type (this
                # channel's rule — gaming or reaction only, ever, on
                # YouTube — is unconditional), so the gate always runs;
                # there's nothing left it's safe to skip.
                gate_job_match = re.match(r"^(.+?)_window(\d+)", content_id)
                gate_job_name = gate_job_match.group(1) if gate_job_match else content_id
                content_ok, content_reason, content_advisory = verify_content_type(
                    gate_job_name, item.get("content_type"),
                    item.get("title", ""), root=ROOT,
                )
                if not content_ok:
                    item["status"] = "error"
                    item["error"] = f"content-safety gate: {content_reason}"
                    published.append(item)
                    continue
                if content_advisory:
                    print(f"publish_scheduler: {content_id} — {content_advisory}")

                # Real parent job name for the duplicate-source check —
                # same broad "<parent>_window<NN>[_platform]" extraction
                # used by the content-safety gate above, not the narrow
                # jobNNN-only "match" (which is None for named jobs like
                # "apexnba2k2" and would silently skip this check for
                # exactly the job family that caused the real duplicate-
                # download incident this fixes).
                dup_parent_match = re.match(r"^(.+?)_window(\d+)", content_id)
                dup_job_name = dup_parent_match.group(1) if dup_parent_match else content_id
                dup_ok, dup_reason = check_duplicate_source_publish(dup_job_name, root=ROOT)
                if not dup_ok:
                    item["status"] = "error"
                    item["error"] = f"duplicate-source gate: {dup_reason}"
                    published.append(item)
                    continue

                srt_path = None
                thumbnail_path = None
                if sub_window_match and doctor_mod:
                    try:
                        srt_path = doctor_mod.generate_srt_for_window(sub_window_match.group(1), int(sub_window_match.group(2)) - 1)
                    except Exception as srt_err:
                        print(f"publish_scheduler: caption generation failed for {content_id} (continuing without): {srt_err}", flush=True)
                    try:
                        thumbnail_path = doctor_mod.extract_thumbnail_for_window(sub_window_match.group(1), int(sub_window_match.group(2)) - 1)
                    except Exception as thumb_err:
                        print(f"publish_scheduler: thumbnail generation failed for {content_id} (continuing without): {thumb_err}", flush=True)
                result = upload_video(item["video_path"], item["title"], item["description"],
                                       item["tags"], privacy_status="private",
                                       srt_path=srt_path, thumbnail_path=thumbnail_path)
                item["status"] = "published"
                item["result"] = result
                mark_source_published(dup_job_name, root=ROOT)
            elif item["platform"] == "tiktok":
                from tiktok_publish import publish_video
                result = publish_video(item["video_path"], item["title"])
                item["status"] = "published"
                item["result"] = result
            elif item["platform"] == "instagram":
                from instagram_publish import publish_reel
                public_url = item.get("public_url")
                if not public_url:
                    raise RuntimeError(
                        "no public_url set on this queue item — Instagram's API fetches "
                        "the video from a real public URL, it does not accept a local path. "
                        "Run lib/prepare_instagram_hosting.py and redeploy takekash-site-live "
                        "first, then this item will pick up its public_url on the next pass."
                    )
                result = publish_reel(public_url, item["title"] + chr(10) + item["description"], video_path_for_duration_check=item["video_path"])
                item["status"] = "published"
                item["result"] = result
            else:
                item["status"] = "error"
                item["error"] = f"unknown platform: {item['platform']}"
        except Exception as e:
            item["status"] = "error"
            item["error"] = str(e)
            # Real, permanent fix: publish failures used to sit silent
            # in the queue with nothing telling you - same pattern as
            # the real job-completion notification, just for failures,
            # with a distinct error sound so the two are never confused.
            try:
                import subprocess as _sp
                _sp.run(
                    ["osascript", "-e",
                     f"display notification \"{item['platform']} post failed: {str(e)[:120]}\" "
                     f"with title \"Publish Failed — {item.get('content_id', 'unknown')}\" sound name \"Basso\""],
                    check=False, timeout=10,
                )
            except Exception:  # noqa: BLE001 - a notification failing should never break the real job
                pass
        published.append(item)

    if published:
        _save_queue(queue)
    return published


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "process":
        results = process_due_items()
        print(json.dumps(results, indent=2, default=str))
    else:
        print(json.dumps(_load_queue(), indent=2))
