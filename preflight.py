#!/usr/bin/env python3
"""
preflight.py [job_id]

Real, automated verification run before every job launch — the direct
answer to "never assume, always seek proper results, execute problems
automatically." Catches the exact class of bug that wasted time
tonight (a dead import that passed every syntax check but failed at
actual runtime) by ACTUALLY IMPORTING every core module, not just
checking syntax. Auto-fixes what's safely fixable; fails fast with a
clear reason for anything that needs a human.

Exit code 0 = safe to proceed. Non-zero = something needs attention,
printed clearly, nothing launched.
"""
import importlib
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))

# Every module a real job launch actually depends on — checked by REAL
# import, not py_compile (which only validates syntax, not whether the
# imports inside actually resolve — this exact gap let a dead import
# ship undetected through every "syntax ok" check tonight).
CORE_MODULES = [
    ("lib", "jobstate"), ("lib", "progress"), ("lib", "diagnose"),
    ("lib", "visual_analysis"), ("lib", "face_tracking"), ("lib", "audio_analysis"),
    ("lib", "fetch_url"), ("lib", "list_channel_videos"), ("lib", "organize_output"),
    ("skills/rough-cut", "cut_engine"),
    ("skills/graphics-plan", "beat_planner"), ("skills/graphics-plan", "render"),
    ("skills/clip-select", "clip_select"), ("skills/clip-select", "build_montage"),
]

REQUIRED_PACKAGES = ["faster_whisper", "fastapi", "cv2", "yt_dlp", "PIL"]


def check_real_imports():
    problems = []
    for rel_dir, mod_name in CORE_MODULES:
        script = f"""
import sys
sys.path.insert(0, {rel_dir!r})
sys.path.insert(0, 'lib')
sys.path.insert(0, 'skills/graphics-plan')
import {mod_name}
"""
        result = subprocess.run([sys.executable, "-c", script], cwd=ROOT,
                                 capture_output=True, text=True)
        if result.returncode != 0:
            last_line = result.stderr.strip().splitlines()[-1] if result.stderr.strip() else "unknown error"
            problems.append(f"{rel_dir}/{mod_name}.py fails to import: {last_line}")
    return problems


def check_dependencies():
    problems = []
    for pkg in REQUIRED_PACKAGES:
        result = subprocess.run([sys.executable, "-c", f"import {pkg}"],
                                 capture_output=True, text=True)
        if result.returncode != 0:
            problems.append(f"required package '{pkg}' not importable in this venv — "
                             f"check you're in the right venv and it's installed")
    return problems


def check_and_fix_stale_lock(job_id):
    """Auto-fix: a lock pointing at a dead PID is safe to clear
    automatically — this is exactly the kind of thing that should never
    need a human to notice and act on."""
    if not job_id:
        return None
    lock_path = os.path.join(ROOT, "projects", job_id, ".lock")
    if not os.path.exists(lock_path):
        return None
    try:
        with open(lock_path) as f:
            pid = int(f.read().strip())
        os.kill(pid, 0)  # check existence, don't actually signal
        return f"job '{job_id}' has an ACTIVE lock (pid {pid} is running) — a launch would correctly be refused, this is not a bug"
    except ProcessLookupError:
        os.remove(lock_path)
        return f"auto-fixed: removed stale lock for '{job_id}' (pid was not running)"
    except (ValueError, OSError):
        os.remove(lock_path)
        return f"auto-fixed: removed unreadable/corrupt lock for '{job_id}'"


def check_disk_space(min_free_gb=5):
    try:
        stat = os.statvfs(ROOT)
        free_gb = (stat.f_bavail * stat.f_frsize) / (1024 ** 3)
    except Exception:
        return None
    if free_gb < min_free_gb:
        return f"only {free_gb:.1f}GB free disk space (threshold {min_free_gb}GB)"
    return None


def main():
    job_id = sys.argv[1] if len(sys.argv) > 1 else None
    blocking_problems = []
    notes = []

    import_problems = check_real_imports()
    if import_problems:
        blocking_problems.extend(import_problems)

    dep_problems = check_dependencies()
    if dep_problems:
        blocking_problems.extend(dep_problems)

    disk_problem = check_disk_space()
    if disk_problem:
        notes.append(f"WARNING: {disk_problem}")  # warn, don't block — not auto-fixable safely

    lock_note = check_and_fix_stale_lock(job_id)
    if lock_note:
        if "ACTIVE lock" in lock_note:
            blocking_problems.append(lock_note)
        else:
            notes.append(lock_note)

    for note in notes:
        print(f"preflight: {note}")

    if blocking_problems:
        print("preflight: BLOCKING problems found — not safe to launch:")
        for p in blocking_problems:
            print(f"  - {p}")
        sys.exit(1)

    print("preflight: all checks passed — real imports verified, dependencies confirmed, no stale locks blocking")
    sys.exit(0)


if __name__ == "__main__":
    main()
