#!/usr/bin/env python3
"""
lib/progress.py

Lightweight progress reporting, separate from job.json's step-done tracking.
job.json answers "which steps are done" (coarse, per-step). progress.json
answers "how far through the CURRENT step are we" (fine-grained, updated
frequently) — this is what makes a real percentage/ETA possible instead of
just watching CPU time climb in `ps`.

Usage from within a long-running step (e.g. whisper transcription):
    from progress import report
    report(job, stage="transcribing", percent=42.5, detail="at 1234s of 3000s")

Usage from a tracker/dashboard:
    from progress import read
    p = read(job)  # -> dict or None
"""
import json
import os
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _path(job, root=None):
    root = root or ROOT
    return os.path.join(root, "projects", job, "progress.json")


def report(job, stage, percent=None, detail="", root=None, started_at=None):
    """Overwrites progress.json for this job. started_at is preserved across
    calls within the same stage so elapsed time is measured from when the
    stage actually began, not from the last write."""
    path = _path(job, root)
    now = time.time()

    existing_started = None
    if os.path.exists(path):
        try:
            with open(path) as f:
                existing = json.load(f)
            if existing.get("stage") == stage:
                existing_started = existing.get("started_at")
        except Exception:
            pass

    data = {
        "job": job,
        "stage": stage,
        "percent": percent,
        "detail": detail,
        "started_at": started_at or existing_started or now,
        "updated_at": now,
    }
    tmp = path + ".tmp"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(tmp, "w") as f:
        json.dump(data, f)
    os.replace(tmp, path)


def read(job, root=None):
    path = _path(job, root)
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None


def clear(job, root=None):
    path = _path(job, root)
    if os.path.exists(path):
        os.remove(path)


def main(argv):
    if len(argv) < 3:
        return 1
    job, stage = argv[1], argv[2]
    detail = argv[3] if len(argv) > 3 else ""
    report(job, stage, None, detail)
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main(sys.argv))
