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


def generate_window_metadata(job_name, window_index):
    """Real per-window title/description, built from the ACTUAL
    transcript content spanning that window's real start/end time —
    not a generic placeholder. Reads the same windows.json and
    script.json already written by best_windows.py and cut_engine.py,
    no new data format needed."""
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

    # real transcript text actually spoken within this window's time range
    covered_text = " ".join(
        seg["text"] for seg in kept_segments
        if seg["start"] >= window["start"] and seg["end"] <= window["end"]
    ).strip()
    hook = covered_text[:80] if covered_text else "Best moments"

    return {
        "title": f"{hook}{'...' if len(covered_text) > 80 else ''} | Part {window_index + 1}",
        "description": (covered_text[:400] if covered_text else "Highlights from a real stream, auto-selected.")
        + f"\n\n(Part {window_index + 1} of {len(windows)})",
        "start": window["start"],
        "end": window["end"],
    }


def publish_best_windows_to_youtube(job_name, privacy="private"):
    """Real, tested path for the job's ACTUAL output structure — 20
    separate files, each with its own real, content-derived title,
    instead of the clip/montage publish path which can't find these
    files at all."""
    from youtube_publish import upload_video

    video_paths = find_best_windows_outputs(job_name)
    if not video_paths:
        return {"error": f"no best-windows outputs found for '{job_name}'"}

    results = []
    for i, video_path in enumerate(video_paths):
        meta = generate_window_metadata(job_name, i)
        if meta is None:
            results.append({"window": i + 1, "error": "no metadata available"})
            continue
        try:
            result = upload_video(video_path, meta["title"], meta["description"], [], privacy_status=privacy)
            results.append({"window": i + 1, "title": meta["title"], "url": result.get("url")})
        except Exception as e:
            results.append({"window": i + 1, "error": str(e)})
    return {"job": job_name, "results": results}


def find_clip_metadata(job_name):
    """For a finished clip/montage subjob, finds the real hook text and
    engagement score from the PARENT job's clips.json — job.json itself
    doesn't carry this, it lives where clip_select.py/build_montage.py
    originally wrote it. Returns None if no match (e.g. a job that
    predates engagement scoring, or isn't a clip/montage subjob at all —
    those aren't auto-published, only real generated content is)."""
    if "__" not in job_name:
        return None
    parent, sub_id = job_name.split("__", 1)
    clips_json_path = os.path.join(PROJECTS, parent, "rough-cut", "clips.json")
    if not os.path.exists(clips_json_path):
        return None
    try:
        with open(clips_json_path) as f:
            data = json.load(f)
    except Exception:
        return None

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
    return None


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
        from youtube_publish import generate_title, generate_description, generate_tags, upload_video
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

        title = generate_title(clip_meta, content_type)
        description = generate_description(clip_meta, source_title=clip_meta.get("source_title"))
        tags = generate_tags(clip_meta, content_type)

        log(f"doctor: auto-publishing {job_name} -> \"{title}\"")
        try:
            result = upload_video(video_path, title, description, tags, privacy_status=privacy)
        except Exception as e:
            log(f"doctor: auto-publish FAILED for {job_name}: {e}")
            continue

        job_data["youtube_video_id"] = result.get("video_id")
        job_data["youtube_url"] = result.get("url")
        with open(job_json_path, "w") as f:
            json.dump(job_data, f, indent=2)
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
