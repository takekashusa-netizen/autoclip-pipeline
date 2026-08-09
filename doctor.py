#!/usr/bin/env python3
"""
doctor.py [--interval SECONDS] [--once]

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

Run detached, same as everything else tonight:
  nohup python3 doctor.py > doctor.log 2>&1 &
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


def run_checks():
    check_duplicate_processes()
    check_stale_locks()
    check_disk_space()
    check_stalled_progress()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--interval", type=int, default=120)
    p.add_argument("--once", action="store_true")
    args = p.parse_args()

    log(f"doctor: watching (checks every {args.interval}s) — Ctrl+C to stop")
    while True:
        run_checks()
        if args.once:
            break
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
