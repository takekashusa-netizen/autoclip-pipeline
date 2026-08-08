#!/usr/bin/env python3
"""
track.py <job> [job2 ...] [--interval N]

Live dashboard for one or more jobs — current step, percent complete where
available, elapsed time, and an estimated time remaining. Reads job.json
(coarse: which of the 7 steps is done) and progress.json (fine-grained:
percent through the CURRENT step, written by cut_engine.py during whisper
transcription and by progress_report() at other stage transitions).

ETA is a simple linear projection from elapsed-time-so-far and percent-
complete-so-far within the current stage — it's an estimate, not a
guarantee, and has no data for stages that don't report a percent (in
which case it just shows elapsed time with no ETA rather than a made-up
number).
"""
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
STEP_ORDER = ["intake", "rough_cut", "graphics", "second_pass",
              "captions", "background_music", "export"]
STEP_LABELS = {
    "intake": "intake", "rough_cut": "rough cut", "graphics": "graphics",
    "second_pass": "review (manual)", "captions": "captions",
    "background_music": "music", "export": "export",
}


def fmt_duration(seconds):
    if seconds is None:
        return "?"
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h{m:02d}m"
    if m:
        return f"{m}m{s:02d}s"
    return f"{s}s"


def bar(percent, width=24):
    if percent is None:
        return "[" + "?" * width + "]"
    filled = int(width * percent / 100)
    return "[" + "#" * filled + "-" * (width - filled) + f"] {percent:5.1f}%"


def load_job(job):
    path = os.path.join(ROOT, "projects", job, "job.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None


def load_progress(job):
    path = os.path.join(ROOT, "projects", job, "progress.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None


def current_step(job_data):
    if job_data is None:
        return None
    steps = job_data.get("steps", {})
    for s in STEP_ORDER:
        if steps.get(s, {}).get("status") != "done":
            return s
    return None  # all done


def render_job(job):
    job_data = load_job(job)
    if job_data is None:
        return f"{job}  (no job.json yet — still downloading?)"

    if job_data.get("error"):
        err = str(job_data["error"]).replace("\n", " ")[:100]
        return f"{job}  [FAILED] {err}"

    step = current_step(job_data)
    if step is None:
        return f"{job}  [DONE] all 7 steps complete"

    prog = load_progress(job)
    label = STEP_LABELS.get(step, step)

    # progress.json may be reporting a sub-stage (e.g. "transcribing")
    # rather than exactly matching a job.json step name — show it if present
    if prog and prog.get("stage"):
        label = f"{label} ({prog['stage']})" if prog["stage"] not in (step,) else label

    if prog and prog.get("percent") is not None:
        pct = prog["percent"]
        elapsed = time.time() - prog.get("started_at", time.time())
        eta = None
        if pct > 1:
            eta = elapsed * (100 - pct) / pct
        detail = prog.get("detail", "")
        return (f"{job}  {label:<28} {bar(pct)}  "
                f"elapsed {fmt_duration(elapsed):>7}  eta {fmt_duration(eta):>7}"
                + (f"  ({detail})" if detail else ""))

    elapsed = None
    if prog and prog.get("started_at"):
        elapsed = time.time() - prog["started_at"]
    return (f"{job}  {label:<28} {bar(None)}  "
            f"elapsed {fmt_duration(elapsed):>7}  eta ?")


def main():
    args = sys.argv[1:]
    interval = 5
    if "--interval" in args:
        i = args.index("--interval")
        interval = int(args[i + 1])
        del args[i:i + 2]

    jobs = args
    if not jobs:
        projects_dir = os.path.join(ROOT, "projects")
        if os.path.isdir(projects_dir):
            jobs = sorted(
                d for d in os.listdir(projects_dir)
                if os.path.isfile(os.path.join(projects_dir, d, "job.json"))
            )
    if not jobs:
        print("no jobs found")
        return

    try:
        while True:
            os.system("clear")
            print(f"autoclip-pipeline — live status ({time.strftime('%H:%M:%S')})")
            print("=" * 78)
            for job in jobs:
                print(render_job(job))
            print("=" * 78)
            print("Ctrl+C to stop watching (jobs keep running in their own terminal)")
            time.sleep(interval)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
