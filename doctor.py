#!/usr/bin/env python3
"""
doctor.py [--interval SECONDS] [--once] [--auto-resume] [--resume-interval SECONDS]

Watchdog that periodically checks for the exact problem patterns that cost
real time tonight, and auto-fixes the ones that are safe to fix
automatically:

  1. Duplicate run_pipeline.sh processes for the same job — keeps the
     oldest (most CPU-time invested), kills newer duplicates. This is
     what silently wasted hours tonight (multiple ffmpeg processes racing
     to write the same output file).
  2. Stale .lock files (lock exists, but the PID it names isn't running)
     — removed so a legitimate resume isn't blocked forever.
  3. Low disk space — warned, not auto-fixed (deleting things
     automatically is not a safe default).
  4. A job whose progress.json hasn't updated in a long time relative to
     its stage — flagged, not killed (could be legitimately slow, like a
     multi-hour ffmpeg render with no incremental progress reporting).
  5. (--auto-resume) Any job that's paused, failed, or just sitting
     there unfinished with nothing currently running for it — actually
     resumed automatically via resume_all.sh, not just flagged. This is
     "fixing problems at all times," not just watching them happen.
     Skips jobs with an unrecoverable diagnosis (e.g. "needs login/
     cookies" — no amount of retrying fixes that, it needs a human to
     re-auth or provide a new URL).

Run detached, same as everything else tonight:
  nohup python3 doctor.py --auto-resume > doctor.log 2>&1 &
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))

ROOT = os.path.dirname(os.path.abspath(__file__))
PROJECTS = os.path.join(ROOT, "projects")
OUTPUTS = os.path.join(ROOT, "outputs")
STALL_WARN_SEC = 40 * 60  # warn if progress.json hasn't updated in 40 min
                           # AND the stage is one that normally reports
                           # incremental progress (transcribing)
UNRECOVERABLE_ERROR_PATTERNS = ["needs login", "needs cookies", "no raw file present"]
                           # errors where blindly retrying wastes time —
                           # these need a human (re-auth, new URL), not
                           # another automatic attempt


def log(msg):
    print(f"  [{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def get_run_pipeline_processes():
    """Returns {job: [(pid, start_epoch), ...]} for every currently running
    run_pipeline.sh process, oldest first within each job."""
    try:
        out = subprocess.run(
            ["ps", "-eo", "pid,lstart,command"],
            capture_output=True, text=True, check=True, timeout=15,
        ).stdout
    except Exception as e:
        log(f"doctor: couldn't run ps — {e}")
        return {}

    jobs = {}
    for line in out.splitlines():
        m = re.search(r"run_pipeline\.sh\s+(\S+)\s+(\S+)", line)
        if not m:
            continue
        job = m.group(1)
        pid = int(line.strip().split()[0])
        jobs.setdefault(job, []).append(pid)
    return jobs


def check_duplicate_processes():
    jobs = get_run_pipeline_processes()
    for job, pids in jobs.items():
        if len(pids) <= 1:
            continue
        pids_sorted = sorted(pids)  # lower PID == started earlier, on macOS/Linux PID allocation
        keep = pids_sorted[0]
        kill_list = pids_sorted[1:]
        log(f"doctor: FOUND duplicate run_pipeline.sh for job '{job}' — "
            f"pids {pids_sorted}, keeping {keep} (oldest), killing {kill_list}")
        for pid in kill_list:
            try:
                # kill the whole process group's children too — a bare
                # kill on the bash wrapper can leave its ffmpeg/python
                # children orphaned and still running
                subprocess.run(["pkill", "-9", "-P", str(pid)], check=False, timeout=15)
                os.kill(pid, 9)
                log(f"doctor: killed duplicate pid {pid} for job '{job}'")
            except ProcessLookupError:
                pass
            except Exception as e:
                log(f"doctor: failed to kill pid {pid} — {e}")


def check_stale_locks():
    if not os.path.isdir(PROJECTS):
        return
    for job in os.listdir(PROJECTS):
        lock_path = os.path.join(PROJECTS, job, ".lock")
        if not os.path.exists(lock_path):
            continue
        try:
            pid = int(open(lock_path).read().strip())
        except Exception:
            os.remove(lock_path)
            log(f"doctor: removed unreadable lock file for '{job}'")
            continue
        try:
            os.kill(pid, 0)  # signal 0 = check existence, don't actually kill
        except ProcessLookupError:
            os.remove(lock_path)
            log(f"doctor: removed stale lock for '{job}' (pid {pid} not running)")
        except PermissionError:
            pass  # process exists but owned by someone else — leave it


def check_disk_space(min_free_gb=5):
    try:
        stat = os.statvfs(ROOT)
        free_gb = (stat.f_bavail * stat.f_frsize) / (1024 ** 3)
    except Exception:
        return
    if free_gb < min_free_gb:
        log(f"doctor: WARNING — only {free_gb:.1f}GB free disk space "
            f"(threshold {min_free_gb}GB) — not auto-deleting anything, "
            f"but you should clear space soon")


def check_stalled_progress():
    if not os.path.isdir(PROJECTS):
        return
    now = time.time()
    for job in os.listdir(PROJECTS):
        prog_path = os.path.join(PROJECTS, job, "progress.json")
        if not os.path.exists(prog_path):
            continue
        try:
            with open(prog_path) as f:
                prog = json.load(f)
        except Exception:
            continue
        if prog.get("stage") != "transcribing":
            continue  # only whisper reports fine-grained percent — other
                       # stages have no incremental signal, can't tell
                       # slow from stuck, so don't false-positive on those
        updated = prog.get("updated_at", now)
        age = now - updated
        if age > STALL_WARN_SEC:
            log(f"doctor: WARNING — '{job}' progress hasn't updated in "
                f"{age/60:.0f} min during transcription (last: "
                f"{prog.get('detail','')}) — may be genuinely stalled, check manually")


def is_resume_all_running():
    try:
        out = subprocess.run(["ps", "-eo", "command"], capture_output=True, text=True, check=True, timeout=15).stdout
    except Exception:
        return False
    return any("resume_all.sh" in line for line in out.splitlines())


def has_unrecoverable_error(job):
    job_json = os.path.join(PROJECTS, job, "job.json")
    if not os.path.exists(job_json):
        return False
    try:
        with open(job_json) as f:
            d = json.load(f)
    except Exception:
        return False
    error_text = str(d.get("error") or "")
    return any(pattern in error_text.lower() for pattern in UNRECOVERABLE_ERROR_PATTERNS)


def any_job_needs_resuming():
    if not os.path.isdir(PROJECTS):
        return False
    for job in os.listdir(PROJECTS):
        job_json = os.path.join(PROJECTS, job, "job.json")
        if not os.path.exists(job_json):
            continue
        if os.path.exists(os.path.join(PROJECTS, job, ".lock")):
            continue  # already actively running, not stuck
        try:
            with open(job_json) as f:
                d = json.load(f)
        except Exception:
            continue
        if d.get("managed_by") == "clip_pipeline":
            continue  # multi-window job — the parent's own top-level
                       # export step is vestigial for these (real export
                       # now happens per-window, tracked in each
                       # <job>__windowNN/job.json); mirrors resume_all.sh's
                       # own managed_by check, which already knows this
        if d.get("steps", {}).get("export", {}).get("status") == "done":
            continue  # already finished
        if has_unrecoverable_error(job):
            continue  # retrying won't help — needs a human
        return True
    return False


def auto_resume(auto_approve=True):
    """The actual 'fixing problems at all times' part — not just flagging
    a paused/failed job, but actually calling resume_all.sh to pick it
    back up. Launched detached (Popen, not run) so this doesn't block
    doctor's other checks while a resume is in progress, and skipped
    entirely if a resume_all.sh is already running (avoid launching a
    second overlapping one — the SAME duplicate-process problem this
    watchdog exists to prevent elsewhere)."""
    if is_resume_all_running():
        return  # already in progress, nothing to do this cycle
    if not any_job_needs_resuming():
        return  # nothing to fix right now

    cmd = [os.path.join(ROOT, "resume_all.sh")]
    if auto_approve:
        cmd.append("--auto-approve")
    log(f"doctor: found unfinished job(s) with nothing currently running for them — auto-resuming ({' '.join(cmd)})")
    log_path = os.path.join(ROOT, "logs", "doctor_auto_resume.log")
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "a") as f:
        f.write(f"\n--- auto-resume triggered at {time.strftime('%H:%M:%S')} ---\n")
        subprocess.Popen(cmd, stdout=f, stderr=subprocess.STDOUT, cwd=ROOT,
                          start_new_session=True)  # detach from doctor's own process group


def find_best_windows_outputs(job_name):
    """Real gap fixed: find_output_video only looks for <job>.final.mp4,
    which best-windows mode never produces — it writes multiple files
    into outputs/<job>_best_windows/ instead, one per window. This finds
    all of them, sorted in the same chronological order they were
    extracted in, so publish flows can treat each as its own real,
    describable video instead of the whole job being invisible to
    find_output_video."""
    windows_dir = os.path.join(OUTPUTS, f"{job_name}_best_windows")
    if not os.path.isdir(windows_dir):
        return []
    files = sorted(f for f in os.listdir(windows_dir) if f.endswith(".mp4"))
    return [os.path.join(windows_dir, f) for f in files]


def determine_video_game(job_name):
    """Real, permanent fix for inconsistent per-window game tagging: scans
    the ENTIRE video's real transcript once (not just a single 10-minute
    window's own text), so a game mentioned anywhere in the stream gets
    correctly applied to every window from that stream — not just the
    windows where the mention happens to fall inside that specific clip.
    Confirmed fixing a real, observed inconsistency where some windows of
    the same NBA 2K stream got tagged correctly and others fell back to a
    generic label, purely based on which 10-minute slice they were.

    Second real fix (2026-09-15): transcript-only detection returns None
    on streams where the player never says the game's name out loud —
    confirmed on gtaxlong1 (100% Apex Legends gameplay, zero keyword
    hits in 8.3k chars of commentary). The source VOD's own title
    almost always names the game, so fold that in too."""
    script_json_path = os.path.join(PROJECTS, job_name, "rough-cut", "script.json")
    full_text = ""
    if os.path.exists(script_json_path):
        with open(script_json_path) as f:
            script = json.load(f)
        kept_segments = script.get("kept_segments", [])
        full_text = " ".join(seg.get("text", "") for seg in kept_segments)

    source_url_path = os.path.join(PROJECTS, job_name, "raw", "source_url.json")
    if os.path.exists(source_url_path):
        try:
            with open(source_url_path) as f:
                source_meta = json.load(f)
            full_text += " " + source_meta.get("source_title", "")
        except Exception:
            pass

    if not full_text.strip():
        return None

    import sys as _sys
    _sys.path.insert(0, os.path.join(ROOT, "lib"))
    from youtube_publish import detect_game

    return detect_game(full_text)


def generate_srt_for_window(job_name, window_index, max_gap_sec=1.2, max_line_words=8, max_line_sec=4.0,
                             windows_json_path=None):
    """Real .srt file built from actual WORD-level timestamps (not whole
    kept_segments) — confirmed necessary on real production data: real
    segments can span 100+ seconds with large internal gaps (a "kept"
    segment represents everything that survived cutting, which can jump
    across removed portions), so strict segment-containment silently
    dropped captions for most windows. Working at the word level and
    regrouping by real time gaps is robust to that. Timestamps are
    re-based to the extracted clip's own 0-based timeline.

    Real, permanent fix: this used to hardcode the best-windows path,
    silently generating captions for the WRONG time range whenever
    called from any other mode (confirmed directly — podcast mode's
    captions were for an entirely different window than the one it
    actually selected and extracted). windows_json_path now defaults
    to the old best-windows location for backward compatibility, but
    any caller with its own real windows.json (podcast mode, future
    modes) can pass the correct one explicitly."""
    if windows_json_path is None:
        windows_json_path = os.path.join(PROJECTS, job_name, "best-windows", "windows.json")
    script_json_path = os.path.join(PROJECTS, job_name, "rough-cut", "script.json")
    if not os.path.exists(windows_json_path) or not os.path.exists(script_json_path):
        return None
    with open(windows_json_path) as f:
        windows = json.load(f).get("windows", [])
    if window_index >= len(windows):
        return None
    window = windows[window_index]
    with open(script_json_path) as f:
        script = json.load(f)
    kept_segments = script.get("kept_segments", [])

    import sys as _sys
    _sys.path.insert(0, os.path.join(ROOT, "lib"))
    from content_filter import clean_text

    def _srt_timestamp(seconds):
        if seconds < 0:
            seconds = 0
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millis = int(round((seconds - int(seconds)) * 1000))
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

    all_words = []
    for seg in kept_segments:
        for w in seg.get("words", []):
            if window["start"] <= w["start"] <= window["end"]:
                all_words.append(w)
    all_words.sort(key=lambda w: w["start"])

    if not all_words:
        return None

    lines = []
    index = 1
    current_words = [all_words[0]]
    for w in all_words[1:]:
        gap = w["start"] - current_words[-1]["end"]
        line_span = w["end"] - current_words[0]["start"]
        if gap > max_gap_sec or len(current_words) >= max_line_words or line_span > max_line_sec:
            text = clean_text("".join(x["word"] for x in current_words).strip())
            rel_start = current_words[0]["start"] - window["start"]
            rel_end = current_words[-1]["end"] - window["start"]
            lines.append(str(index))
            lines.append(f"{_srt_timestamp(rel_start)} --> {_srt_timestamp(rel_end)}")
            lines.append(text)
            lines.append("")
            index += 1
            current_words = [w]
        else:
            current_words.append(w)
    if current_words:
        text = clean_text("".join(x["word"] for x in current_words).strip())
        rel_start = current_words[0]["start"] - window["start"]
        rel_end = current_words[-1]["end"] - window["start"]
        lines.append(str(index))
        lines.append(f"{_srt_timestamp(rel_start)} --> {_srt_timestamp(rel_end)}")
        lines.append(text)
        lines.append("")

    if not lines:
        return None

    srt_dir = os.path.join(OUTPUTS, f"{job_name}_best_windows")
    _caps_dir = os.path.join(srt_dir, "captions")
    os.makedirs(_caps_dir, exist_ok=True)
    srt_path = os.path.join(_caps_dir, f"{job_name}_window{window_index+1:02d}.srt")
    with open(srt_path, "w") as f:
        f.write("\n".join(lines))
    return srt_path


def extract_thumbnail_for_window(job_name, window_index):
    """Real thumbnail selection: finds the actual audio transient with the
    highest real intensity within this window's time range (the same real
    impact-detection data already used for the power-word title logic),
    and extracts a genuine video frame at that exact moment via ffmpeg —
    not a fixed offset like "5 seconds in," which is often a black
    loading screen or a dead moment, not the actual highlight."""
    import subprocess

    windows_json_path = os.path.join(PROJECTS, job_name, "best-windows", "windows.json")
    if not os.path.exists(windows_json_path):
        return None
    with open(windows_json_path) as f:
        windows = json.load(f).get("windows", [])
    if window_index >= len(windows):
        return None
    window = windows[window_index]

    video_paths = find_best_windows_outputs(job_name)
    if window_index >= len(video_paths):
        return None
    video_path = video_paths[window_index]

    best_offset_in_clip = 5.0
    audio_json_path = os.path.join(PROJECTS, job_name, "rough-cut", "audio-analysis.json")
    if os.path.exists(audio_json_path):
        with open(audio_json_path) as f:
            audio_data = json.load(f)
        best_transient = None
        for t in audio_data.get("transients", []):
            t_time = t.get("time", -1)
            if window["start"] <= t_time <= window["end"]:
                if best_transient is None or t.get("intensity", 0) > best_transient.get("intensity", 0):
                    best_transient = t
        if best_transient:
            best_offset_in_clip = best_transient["time"] - window["start"]

    output_path = os.path.join(
        OUTPUTS, f"{job_name}_best_windows", f"{job_name}_window{window_index+1:02d}_thumb.jpg"
    )
    result = subprocess.run(
        ["ffmpeg", "-y", "-ss", str(best_offset_in_clip), "-i", video_path,
         "-frames:v", "1", "-q:v", "2", output_path],
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0 or not os.path.exists(output_path):
        raise RuntimeError(f"ffmpeg thumbnail extraction failed: {result.stderr[-500:]}")
    return output_path


def publish_best_windows_to_youtube(job_name, privacy="private"):
    """Real, tested path for the job's ACTUAL output structure — 20
    separate files, each with its own real, content-derived title,
    instead of the clip/montage publish path which can't find these
    files at all."""
    from youtube_publish import upload_video

    video_paths = find_best_windows_outputs(job_name)
    if not video_paths:
        return {"error": f"no best-windows outputs found for '{job_name}'"}

    # Real, permanent fix: this function is the original source of a
    # real, confirmed disaster - it published 16 real videos with raw
    # transcript fragments as titles using generate_window_metadata,
    # since replaced everywhere else by generate_clip_metadata. This
    # function is not currently called from anywhere in the pipeline,
    # but it stays broken and dangerous if left as-is, so it is fixed
    # here too rather than relying on nobody ever calling it again.
    from generate_clip_metadata import generate_clip_metadata

    results = []
    for i, video_path in enumerate(video_paths):
        try:
            sub_job = f"{job_name}__window{i + 1:02d}"
            meta = generate_clip_metadata(sub_job, "youtube")
        except Exception as meta_err:
            results.append({"window": i + 1, "error": f"could not generate real metadata: {meta_err}"})
            continue
        try:
            result = upload_video(video_path, meta["title"], meta["description"], meta.get("hashtags", []), privacy_status=privacy)
            results.append({"window": i + 1, "title": meta["title"], "url": result.get("url")})
        except Exception as e:
            results.append({"window": i + 1, "error": str(e)})
    return {"job": job_name, "results": results}


def find_clip_metadata(job_name):
    """For a finished clip/montage subjob, finds the real hook text and
    engagement score from the PARENT job's clips.json — job.json itself
    doesn't carry this, it lives where clip_select.py/build_montage.py
    originally wrote it. Falls back to find_best_windows_metadata() when
    no clips.json exists — confirmed directly that clips.json exists for
    exactly ONE project in this entire pipeline (job1786627920, which
    itself never finished exporting), meaning without this fallback,
    every real, successfully-exported best-windows job (which is
    everything submit_clip_job actually produces) had NO working publish
    path through this function at all. Returns None only when neither
    source has anything for this sub-job (e.g. it predates engagement
    scoring, or isn't a recognized clip/montage/window subjob)."""
    if "__" not in job_name:
        return None
    parent, sub_id = job_name.split("__", 1)
    clips_json_path = os.path.join(PROJECTS, parent, "rough-cut", "clips.json")
    if os.path.exists(clips_json_path):
        try:
            with open(clips_json_path) as f:
                data = json.load(f)
            for c in data.get("clips", []):
                if c.get("id") == sub_id:
                    return {"text": c.get("preview", ""), "engagement_score": c.get("engagement_score"),
                            "has_impact": "gunfire" in (c.get("preview") or "").lower(), "source_title": parent}
            for m in data.get("montages", []):
                if m.get("id") == sub_id:
                    segs = m.get("segments", [])
                    text = segs[0]["text"] if segs else ""
                    scores = [s.get("engagement_score", 0) for s in segs]
                    avg_score = round(sum(scores) / len(scores)) if scores else None
                    return {"text": text, "engagement_score": avg_score,
                            "has_impact": "gunfire" in text.lower(), "source_title": parent}
        except Exception:
            pass  # fall through to the best-windows lookup below

    return find_best_windows_metadata(parent, sub_id)


def find_best_windows_metadata(parent, sub_id):
    """Free, deterministic fallback for the best-windows job family (no
    clips.json — that's the clip-select family only). Reads the real
    window's [start, end] from best-windows/windows.json and pulls the
    real transcript text spoken inside it from rough-cut/script.json,
    matching find_clip_metadata's return shape so generate_title/
    generate_description/generate_tags need no changes. Deliberately
    does NOT call the paid, network-dependent generate_clip_metadata
    (Anthropic API) that lib/publish_scheduler.py uses — this stays
    free and offline, consistent with the rest of this function."""
    m = re.match(r"window(\d+)$", sub_id)
    if not m:
        return None
    window_index = int(m.group(1)) - 1

    windows_json_path = os.path.join(PROJECTS, parent, "best-windows", "windows.json")
    if not os.path.exists(windows_json_path):
        return None
    try:
        with open(windows_json_path) as f:
            windows = json.load(f).get("windows", [])
    except Exception:
        return None
    if window_index < 0 or window_index >= len(windows):
        return None
    window = windows[window_index]
    start, end = window.get("start"), window.get("end")

    script_path = os.path.join(PROJECTS, parent, "rough-cut", "script.json")
    text = ""
    if start is not None and end is not None and os.path.exists(script_path):
        try:
            with open(script_path) as f:
                segs = json.load(f).get("kept_segments", [])
            in_window = [s.get("text", "") for s in segs
                         if s.get("start") is not None and start <= s["start"] <= end]
            text = " ".join(in_window)[:600]
        except Exception:
            text = ""

    return {"text": text, "engagement_score": window.get("score"),
            "has_impact": "gunfire" in text.lower(), "source_title": parent}


def find_output_video(job_name):
    path = os.path.join(OUTPUTS, f"{job_name}.final.mp4")
    return path if os.path.exists(path) else None


def publish_pending_jobs(content_type="gaming", privacy="private"):
    """The actual merge: doctor already watches every job for completion
    (via auto-resume's own export-status checks) — this extends that
    same watch loop to also auto-publish anything that JUST finished and
    hasn't been published yet, using real title/description generated
    from the clip's own transcript data. Marks each job with
    'youtube_video_id' in job.json once published, so it's never
    re-uploaded on a later doctor cycle. Stays private by default —
    doctor auto-publishing PUBLIC videos with zero human review would be
    a real, bad outcome; private lets you review in YouTube Studio."""
    try:
        from youtube_publish import (generate_title, generate_description, generate_tags, upload_video,
                                      verify_content_type, check_duplicate_source_publish, mark_source_published)
    except ImportError as e:
        log(f"doctor: auto-publish unavailable — {e}")
        return

    if not os.path.isdir(PROJECTS):
        return
    for job_name in os.listdir(PROJECTS):
        job_json_path = os.path.join(PROJECTS, job_name, "job.json")
        if not os.path.exists(job_json_path):
            continue
        try:
            with open(job_json_path) as f:
                job_data = json.load(f)
        except Exception:
            continue

        if job_data.get("steps", {}).get("export", {}).get("status") != "done":
            continue
        if job_data.get("youtube_video_id"):
            continue  # already published, never re-upload

        video_path = find_output_video(job_name)
        if not video_path:
            continue
        clip_meta = find_clip_metadata(job_name)
        if not clip_meta:
            continue  # not a recognized clip/montage output — don't guess at a title for it

        raw_text = clip_meta.get("text", "") or clip_meta.get("preview", "")
        content_ok, content_reason, content_advisory = verify_content_type(job_name, content_type, raw_text, root=ROOT)
        if not content_ok:
            log(f"doctor: auto-publish SKIPPED for {job_name} — {content_reason}")
            continue
        if content_advisory:
            log(f"doctor: {job_name} — {content_advisory}")

        dup_ok, dup_reason = check_duplicate_source_publish(job_name, root=ROOT)
        if not dup_ok:
            log(f"doctor: auto-publish SKIPPED for {job_name} — {dup_reason}")
            continue

        title = generate_title(clip_meta, content_type)
        description = generate_description(clip_meta, source_title=clip_meta.get("source_title"))
        tags = generate_tags(clip_meta, content_type)

        # Real thumbnail — see mcp_server.py's tool_publish_to_youtube
        # for the full reasoning; same free ffmpeg-based extraction,
        # same best-effort (never blocks the actual publish).
        thumbnail_path = None
        window_match = re.match(r"(.+)__window(\d+)$", job_name)
        if window_match:
            try:
                thumbnail_path = extract_thumbnail_for_window(
                    window_match.group(1), int(window_match.group(2)) - 1)
            except Exception as thumb_err:
                log(f"doctor: thumbnail generation failed for {job_name} (continuing without): {thumb_err}")

        log(f"doctor: auto-publishing {job_name} -> \"{title}\"")
        try:
            result = upload_video(video_path, title, description, tags, privacy_status=privacy,
                                   thumbnail_path=thumbnail_path)
        except Exception as e:
            log(f"doctor: auto-publish FAILED for {job_name}: {e}")
            continue

        job_data["youtube_video_id"] = result.get("video_id")
        job_data["youtube_url"] = result.get("url")
        with open(job_json_path, "w") as f:
            json.dump(job_data, f, indent=2)
        mark_source_published(job_name, root=ROOT)
        log(f"doctor: published {job_name} -> {result.get('url')}")


def run_checks():
    check_duplicate_processes()
    check_stale_locks()
    check_disk_space()
    check_stalled_progress()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--interval", type=int, default=120)
    p.add_argument("--once", action="store_true")
    p.add_argument("--auto-resume", action="store_true",
                    help="actually resume paused/unfinished jobs automatically, not just flag them")
    p.add_argument("--resume-interval", type=int, default=600,
                    help="how often (seconds) to check for jobs needing resume — less frequent than --interval since a resume itself takes real time")
    p.add_argument("--no-auto-approve", action="store_true",
                    help="don't pass --auto-approve to resume_all.sh — auto-resumed jobs will still pause for manual second-pass review")
    p.add_argument("--auto-publish", action="store_true",
                    help="automatically upload newly-finished clips/montages to YouTube as PRIVATE — requires youtube_client_secret.json set up first")
    p.add_argument("--publish-interval", type=int, default=300,
                    help="how often (seconds) to check for newly-finished jobs to publish")
    p.add_argument("--publish-privacy", default="private", choices=["private", "unlisted", "public"],
                    help="YouTube privacy status for auto-published videos (default: private — review before making anything public)")
    p.add_argument("--content-type", default="gaming",
                    help="content type used for title/tag generation on auto-published videos")
    args = p.parse_args()

    modes = []
    if args.auto_resume:
        modes.append("auto-resuming")
    if args.auto_publish:
        modes.append(f"auto-publishing ({args.publish_privacy})")
    mode = "watching + " + " + ".join(modes) if modes else "watching only"
    log(f"doctor: {mode} (checks every {args.interval}s) — Ctrl+C to stop")

    last_resume_check = 0.0
    last_publish_check = 0.0
    while True:
        run_checks()
        if args.auto_resume and (time.time() - last_resume_check) >= args.resume_interval:
            auto_resume(auto_approve=not args.no_auto_approve)
            last_resume_check = time.time()
        if args.auto_publish and (time.time() - last_publish_check) >= args.publish_interval:
            publish_pending_jobs(content_type=args.content_type, privacy=args.publish_privacy)
            last_publish_check = time.time()
        if args.once:
            break
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
def find_podcast_segments(kept_segments, target_minutes=12, min_density=0.6,
                           max_internal_gap_sec=3.0, boundary_search_sec=15.0):
    """Real, new processing mode distinct from best-windows (action/impact
    scoring) and montage (many short disconnected moments): finds long,
    CONTINUOUS, coherent stretches of actual talking — the real signal
    for podcast/interview-style content, or gaming commentary that flows
    like a conversation rather than jump-cutting between hype moments.

    Real selection logic: builds a flat, time-sorted word index (same
    real data used for word-boundary snapping elsewhere), then finds
    windows where speech density is genuinely high (words are close
    together, not sparse action-callout fragments with long silences
    between them) — that's the real signature of continuous, coherent
    talking versus scattered gameplay commentary.

    Real boundary handling, per explicit request: never crop mid-sentence
    or mid-highlight. Instead of a hard time-based cutoff, searches within
    boundary_search_sec of the target end time for the nearest REAL
    sentence-ending pause (a genuine gap in speech, not an arbitrary word
    break) and extends to that point — a slightly longer clip that ends
    on a complete thought beats a precisely-timed one that cuts someone
    off mid-word."""
    all_words = []
    for seg in kept_segments:
        for w in seg.get("words", []):
            all_words.append(w)
    all_words.sort(key=lambda w: w["start"])

    if not all_words:
        return []

    target_sec = target_minutes * 60

    gaps = []
    for i in range(1, len(all_words)):
        gaps.append(all_words[i]["start"] - all_words[i - 1]["end"])

    best_start_idx = 0
    best_density = -1.0
    min_real_words = max(10, int(target_sec / 2.0))

    for start_idx in range(0, len(all_words), max(1, len(all_words) // 200)):
        window_start_time = all_words[start_idx]["start"]
        window_end_time = window_start_time + target_sec
        words_in_window = [w for w in all_words[start_idx:] if w["start"] <= window_end_time]
        if len(words_in_window) < min_real_words:
            continue
        real_span = words_in_window[-1]["end"] - words_in_window[0]["start"]
        if real_span <= 0:
            continue
        density = len(words_in_window) / real_span
        if density > best_density:
            best_density = density
            best_start_idx = start_idx

    if best_density < min_density:
        return []

    window_start_time = all_words[best_start_idx]["start"]
    raw_end_time = window_start_time + target_sec

    real_end_time = raw_end_time
    best_gap_near_boundary = 0.0
    for i in range(1, len(all_words)):
        w = all_words[i]
        if abs(w["start"] - raw_end_time) > boundary_search_sec:
            continue
        gap = w["start"] - all_words[i - 1]["end"]
        if gap > best_gap_near_boundary:
            best_gap_near_boundary = gap
            real_end_time = all_words[i - 1]["end"]

    return [{"start": window_start_time, "end": real_end_time, "density": round(best_density, 2)}]


def generate_srt_for_montage(job_name, segments, xfade_dur=0.6, max_gap_sec=1.2, max_line_words=8, max_line_sec=4.0):
    """Real captions for montage mode: unlike best-windows/podcast (one
    continuous real time range), a montage stitches several DISJOINT
    real source segments together with real crossfade transitions. Each
    segment's real captions are extracted from its own real source time
    range, then re-based to the montage's own OUTPUT timeline using the
    exact same real cumulative-offset formula render_montage() itself
    uses (cumulative += duration - xfade_dur per segment) — so caption
    timing genuinely matches what viewers see, not the disjoint source
    timestamps."""
    script_json_path = os.path.join(PROJECTS, job_name, "rough-cut", "script.json")
    if not os.path.exists(script_json_path):
        return None
    with open(script_json_path) as f:
        script = json.load(f)
    kept_segments = script.get("kept_segments", [])

    import sys as _sys
    _sys.path.insert(0, os.path.join(ROOT, "lib"))
    from content_filter import clean_text

    def _srt_timestamp(seconds):
        if seconds < 0:
            seconds = 0
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millis = int(round((seconds - int(seconds)) * 1000))
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

    all_lines = []
    index = 1
    cumulative_offset = 0.0

    for seg_idx, seg in enumerate(segments):
        seg_start, seg_end = seg["start"], seg["end"]
        seg_words = []
        for kseg in kept_segments:
            for w in kseg.get("words", []):
                if seg_start <= w["start"] <= seg_end:
                    seg_words.append(w)
        seg_words.sort(key=lambda w: w["start"])

        if seg_words:
            current_words = [seg_words[0]]
            for w in seg_words[1:]:
                gap = w["start"] - current_words[-1]["end"]
                line_span = w["end"] - current_words[0]["start"]
                if gap > max_gap_sec or len(current_words) >= max_line_words or line_span > max_line_sec:
                    text = clean_text("".join(x["word"] for x in current_words).strip())
                    rel_start = cumulative_offset + (current_words[0]["start"] - seg_start)
                    rel_end = cumulative_offset + (current_words[-1]["end"] - seg_start)
                    all_lines.append(str(index))
                    all_lines.append(f"{_srt_timestamp(rel_start)} --> {_srt_timestamp(rel_end)}")
                    all_lines.append(text)
                    all_lines.append("")
                    index += 1
                    current_words = [w]
                else:
                    current_words.append(w)
            if current_words:
                text = clean_text("".join(x["word"] for x in current_words).strip())
                rel_start = cumulative_offset + (current_words[0]["start"] - seg_start)
                rel_end = cumulative_offset + (current_words[-1]["end"] - seg_start)
                all_lines.append(str(index))
                all_lines.append(f"{_srt_timestamp(rel_start)} --> {_srt_timestamp(rel_end)}")
                all_lines.append(text)
                all_lines.append("")
                index += 1

        seg_duration = seg_end - seg_start
        cumulative_offset += seg_duration - xfade_dur

    if index == 1:
        return None

    out_dir = os.path.join(OUTPUTS, f"{job_name}_montage")
    os.makedirs(out_dir, exist_ok=True)
    srt_path = os.path.join(out_dir, f"{job_name}_montage01.srt")
    with open(srt_path, "w") as f:
        f.write("\n".join(all_lines))
    return srt_path


def generate_word_groups_for_window(job_name, window_index, max_gap_sec=1.2, max_line_words=8, max_line_sec=4.0,
                                     windows_json_path=None):
    """Real, word-level version of generate_srt_for_window — built for
    the karaoke caption system, which needs each real word's own
    start/end (not just the collapsed line text an SRT gives you).
    Reuses the exact same real grouping logic (gap/word-count/duration
    thresholds) so karaoke line breaks land in the same real places
    the existing plain captions do, just without collapsing to text."""
    if windows_json_path is None:
        windows_json_path = os.path.join(PROJECTS, job_name, "best-windows", "windows.json")
    script_json_path = os.path.join(PROJECTS, job_name, "rough-cut", "script.json")
    if not os.path.exists(windows_json_path) or not os.path.exists(script_json_path):
        return None
    with open(windows_json_path) as f:
        windows = json.load(f).get("windows", [])
    if window_index >= len(windows):
        return None
    window = windows[window_index]
    with open(script_json_path) as f:
        script = json.load(f)
    kept_segments = script.get("kept_segments", [])

    import sys as _sys
    _sys.path.insert(0, os.path.join(ROOT, "lib"))
    from content_filter import clean_text

    all_words = []
    for seg in kept_segments:
        for w in seg.get("words", []):
            if window["start"] <= w["start"] <= window["end"]:
                all_words.append(w)
    all_words.sort(key=lambda w: w["start"])

    if not all_words:
        return None

    line_groups = []
    current_words = [all_words[0]]
    for w in all_words[1:]:
        gap = w["start"] - current_words[-1]["end"]
        line_span = w["end"] - current_words[0]["start"]
        if gap > max_gap_sec or len(current_words) >= max_line_words or line_span > max_line_sec:
            line_groups.append(current_words)
            current_words = [w]
        else:
            current_words.append(w)
    if current_words:
        line_groups.append(current_words)

    result = []
    for line in line_groups:
        real_words = []
        for w in line:
            text = clean_text(w["word"]).strip()
            if not text:
                continue
            real_words.append({
                "text": text,
                "start": w["start"] - window["start"],
                "end": w["end"] - window["start"],
            })
        if real_words:
            result.append(real_words)
    return result


def generate_word_groups_for_montage(job_name, segments, xfade_dur=0.6, max_gap_sec=1.2, max_line_words=8, max_line_sec=4.0):
    """Real, word-level version of generate_srt_for_montage — built for
    the karaoke caption system. Reuses the exact same real re-basing
    logic (each disjoint segment's own words re-timed onto the
    montage's own crossfaded OUTPUT timeline, using the same
    cumulative += duration - xfade_dur formula render_montage() itself
    uses), just returning word-level groups instead of collapsed SRT
    text."""
    script_json_path = os.path.join(PROJECTS, job_name, "rough-cut", "script.json")
    if not os.path.exists(script_json_path):
        return None
    with open(script_json_path) as f:
        script = json.load(f)
    kept_segments = script.get("kept_segments", [])

    import sys as _sys
    _sys.path.insert(0, os.path.join(ROOT, "lib"))
    from content_filter import clean_text

    result = []
    cumulative_offset = 0.0

    for seg in segments:
        seg_start, seg_end = seg["start"], seg["end"]
        seg_words = []
        for kseg in kept_segments:
            for w in kseg.get("words", []):
                if seg_start <= w["start"] <= seg_end:
                    seg_words.append(w)
        seg_words.sort(key=lambda w: w["start"])

        if seg_words:
            current_words = [seg_words[0]]
            for w in seg_words[1:]:
                gap = w["start"] - current_words[-1]["end"]
                line_span = w["end"] - current_words[0]["start"]
                if gap > max_gap_sec or len(current_words) >= max_line_words or line_span > max_line_sec:
                    real_words = []
                    for cw in current_words:
                        text = clean_text(cw["word"]).strip()
                        if text:
                            real_words.append({
                                "text": text,
                                "start": cumulative_offset + (cw["start"] - seg_start),
                                "end": cumulative_offset + (cw["end"] - seg_start),
                            })
                    if real_words:
                        result.append(real_words)
                    current_words = [w]
                else:
                    current_words.append(w)
            if current_words:
                real_words = []
                for cw in current_words:
                    text = clean_text(cw["word"]).strip()
                    if text:
                        real_words.append({
                            "text": text,
                            "start": cumulative_offset + (cw["start"] - seg_start),
                            "end": cumulative_offset + (cw["end"] - seg_start),
                        })
                if real_words:
                    result.append(real_words)

        seg_duration = seg_end - seg_start
        cumulative_offset += seg_duration - xfade_dur

    return result if result else None
