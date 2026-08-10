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
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
PROJECTS = os.path.join(ROOT, "projects")
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
            capture_output=True, text=True, check=True,
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
                subprocess.run(["pkill", "-9", "-P", str(pid)], check=False)
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
        out = subprocess.run(["ps", "-eo", "command"], capture_output=True, text=True, check=True).stdout
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
    args = p.parse_args()

    mode = "watching + auto-resuming" if args.auto_resume else "watching only"
    log(f"doctor: {mode} (checks every {args.interval}s"
        + (f", resume checks every {args.resume_interval}s" if args.auto_resume else "")
        + ") — Ctrl+C to stop")

    last_resume_check = 0.0
    while True:
        run_checks()
        if args.auto_resume and (time.time() - last_resume_check) >= args.resume_interval:
            auto_resume(auto_approve=not args.no_auto_approve)
            last_resume_check = time.time()
        if args.once:
            break
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
